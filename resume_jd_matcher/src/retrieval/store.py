"""Vector store for the RAG knowledge base.

Two backends behind one interface, so condition C does not depend on Chroma
being installable:

* `ChromaStore`  - Chroma, as specified in PS section 5 ("Chroma local vector
  store, open-source, self-hosted").
* `LocalVectorStore` - an in-process numpy cosine index. Roughly 50 chunks fit
  in memory many times over, and it always works.

`make_store` picks Chroma when available and falls back otherwise, and it
*returns the reason*. The store also carries the similarity calibration, because
the raw cosine number a backend produces is not comparable across backends and
must not be thresholded directly.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src import config
from src.retrieval.embeddings import make_embedder


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness check that never raises.

    The first version of the run lock decoded `tasklist` output as strict UTF-8,
    which raises on a non-English Windows and made every PID look dead - so the
    guard was silently disabled. Decode leniently.
    """
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
            ).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001 - liveness is best-effort, never fatal
        return False


def acquire_index_lock(persist_dir: Path) -> Path | None:
    """Serialise access to one vector-index directory across processes.

    The index is a *shared mutable* resource and its path comes from config, so
    without this a second process rebuilding it silently deletes the collection
    a running evaluation is querying - every query then raises `NotFoundError`
    and the condition looks like a model failure. That is exactly what happened
    while producing this report, twice: once with two runs, and once when a
    tool that only wanted a *description* of the index rebuilt it.

    The lock is held for the life of the knowledge base rather than only during
    construction, because the delete-and-recreate happens at construction time
    while the damage shows up on the next query. Rebuilt once per run, read many
    times, so coarse is fine at this size.

    Returns the lock path, or None when the backend keeps no state on disk.
    """
    lock = persist_dir.with_name(persist_dir.name + ".lock")
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - an unwritable lock must not break retrieval
        return None

    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            info = {}
        pid = int(info.get("pid") or 0)
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise RuntimeError(
                f"the retrieval index at {persist_dir} is held by pid {pid} "
                f"(started {info.get('started_at')}). Two processes sharing one index "
                "delete each other's collection mid-query, so this refuses instead of "
                f"returning empty results. Retry when that process exits, or delete {lock}."
            )

    lock.write_text(
        json.dumps({"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}),
        encoding="utf-8",
    )

    def _release() -> None:
        # Cleanup must never mask the run's own result: removing a file can be
        # intercepted by the host environment, and an exception inside an atexit
        # hook prints a traceback that reads like a failure.
        try:
            lock.unlink(missing_ok=True)
        except BaseException:  # noqa: BLE001
            pass

    atexit.register(_release)
    return lock


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: str = ""
    family: str = "generic"
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any], index: int = 0) -> "Chunk":
        return cls(
            chunk_id=str(raw.get("id") or raw.get("chunk_id") or f"chunk_{index:03d}"),
            text=str(raw.get("text", "")).strip(),
            source=str(raw.get("source", "")),
            family=str(raw.get("family", "generic")),
            tags=tuple(raw.get("tags", ()) or ()),
        )


@dataclass
class Retrieved:
    chunk_id: str
    text: str
    score: float          # calibrated 0-1
    raw_similarity: float # what the backend actually returned
    source: str = ""
    family: str = "generic"


@dataclass
class RetrievalResult:
    query: str
    hits: list[Retrieved] = field(default_factory=list)

    @property
    def chunk_ids(self) -> list[str]:
        return [h.chunk_id for h in self.hits]

    @property
    def mean_score(self) -> float:
        if not self.hits:
            return 0.0
        return float(sum(h.score for h in self.hits) / len(self.hits))

    @property
    def top_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0

    def as_prompt_block(self) -> str:
        if not self.hits:
            return "(no reference notes retrieved)"
        lines: list[str] = []
        for hit in self.hits:
            lines.append(f"[{hit.chunk_id} | {hit.source} | score {hit.score:.2f}] {hit.text}")
        return "\n".join(lines)


def calibrate(raw: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return max(0.0, min(1.0, raw))
    return float(max(0.0, min(1.0, (raw - floor) / (ceiling - floor))))


class LocalVectorStore:
    backend_name = "local-numpy"

    def __init__(self, chunks: Sequence[Chunk], embedder: object) -> None:
        self.chunks = list(chunks)
        self.embedder = embedder
        self._matrix = (
            embedder.encode([c.text for c in self.chunks]) if self.chunks else np.zeros((0, 1))
        )

    def query(self, text: str, top_k: int = 4, family: str | None = None) -> list[Retrieved]:
        if not self.chunks:
            return []
        query_vec = self.embedder.encode([text])[0]  # type: ignore[attr-defined]
        scores = self._matrix @ query_vec
        order = np.argsort(-scores)
        out: list[Retrieved] = []
        for idx in order:
            chunk = self.chunks[int(idx)]
            if family and chunk.family not in {"generic", family}:
                continue
            out.append(
                Retrieved(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    score=0.0,
                    raw_similarity=float(scores[int(idx)]),
                    source=chunk.source,
                    family=chunk.family,
                )
            )
            if len(out) >= top_k:
                break
        return out


class ChromaStore:
    backend_name = "chroma"

    def __init__(self, chunks: Sequence[Chunk], embedder: object, persist_dir: Path) -> None:
        import chromadb

        self.chunks = list(chunks)
        self.embedder = embedder
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        collection_name = str(config.get("retrieval", "collection", default="resume_knowledge"))

        # Fresh collection every build: the KB is regenerated from a committed
        # file, so a stale index is a correctness risk, not a cache.
        try:
            self._client.delete_collection(collection_name)
        except Exception:
            pass
        self._collection = self._client.create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )
        if self.chunks:
            self._collection.add(
                ids=[c.chunk_id for c in self.chunks],
                documents=[c.text for c in self.chunks],
                metadatas=[
                    {"source": c.source, "family": c.family, "tags": ",".join(c.tags)}
                    for c in self.chunks
                ],
                embeddings=[list(v) for v in embedder.encode([c.text for c in self.chunks])],  # type: ignore[attr-defined]
            )

    def query(self, text: str, top_k: int = 4, family: str | None = None) -> list[Retrieved]:
        if not self.chunks:
            return []
        where = {"family": {"$in": ["generic", family]}} if family else None
        vector = list(self.embedder.encode([text])[0])  # type: ignore[attr-defined]
        response = self._collection.query(
            query_embeddings=[vector],
            n_results=min(top_k, len(self.chunks)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (response.get("ids") or [[]])[0]
        docs = (response.get("documents") or [[]])[0]
        metas = (response.get("metadatas") or [[]])[0]
        dists = (response.get("distances") or [[]])[0]

        out: list[Retrieved] = []
        for i, chunk_id in enumerate(ids):
            distance = float(dists[i]) if i < len(dists) else 1.0
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            out.append(
                Retrieved(
                    chunk_id=str(chunk_id),
                    text=str(docs[i]) if i < len(docs) else "",
                    score=0.0,
                    raw_similarity=1.0 - distance,  # cosine space
                    source=str(meta.get("source", "")),
                    family=str(meta.get("family", "generic")),
                )
            )
        return out


@dataclass
class KnowledgeBase:
    """The thing the pipeline actually calls."""

    store: Any
    embedder_info: dict[str, Any]
    store_info: dict[str, Any]
    chunk_count: int
    notes: list[str] = field(default_factory=list)
    lock_path: Path | None = None

    @property
    def backend(self) -> str:
        return str(self.store_info.get("backend", "unknown"))

    def close(self) -> None:
        """Release the index lock. Safe to call more than once."""
        if self.lock_path is not None:
            try:
                self.lock_path.unlink(missing_ok=True)
            except BaseException:  # noqa: BLE001
                pass
            self.lock_path = None

    def retrieve(
        self, query: str, top_k: int | None = None, family: str | None = None
    ) -> RetrievalResult:
        top_k = int(top_k or config.get("retrieval", "top_k", default=4))
        floor = float(config.get("retrieval", "similarity_floor", default=0.0))
        ceiling = float(config.get("retrieval", "similarity_ceiling", default=1.0))

        hits = self.store.query(query, top_k=top_k, family=family)
        for hit in hits:
            hit.score = calibrate(hit.raw_similarity, floor, ceiling)
        return RetrievalResult(query=query, hits=hits)

    def describe(self) -> dict[str, Any]:
        return {
            "chunks": self.chunk_count,
            "store": self.store_info,
            "embedder": self.embedder_info,
            "notes": self.notes,
        }


def load_chunks(path: Path | None = None) -> list[Chunk]:
    path = path or config.path("knowledge_base")
    if not path.exists():
        raise FileNotFoundError(
            f"knowledge base not found at {path}. Run: python -m data.knowledge_base.build_kb"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["chunks"] if isinstance(raw, dict) and "chunks" in raw else raw
    max_chars = int(config.get("retrieval", "max_chunk_chars", default=500))
    chunks = [Chunk.from_dict(item, i) for i, item in enumerate(items)]
    over = [c.chunk_id for c in chunks if len(c.text) > max_chars]
    if over:
        raise ValueError(
            f"{len(over)} chunk(s) exceed max_chunk_chars={max_chars}: {over[:5]}. "
            "The Problem Statement commits to chunks under 500 characters."
        )
    return chunks


def build_knowledge_base(
    *,
    backend: str | None = None,
    embedding_backend: str | None = None,
    chunks: Sequence[Chunk] | None = None,
    persist_dir: Path | None = None,
) -> KnowledgeBase:
    """Build the retrieval index.

    `persist_dir` overrides `retrieval.persist_dir`. Callers that belong to one
    evaluation run should pass their own out-dir, so two runs cannot delete each
    other's index (see `acquire_index_lock`).
    """
    backend = (backend or config.get("retrieval", "backend", default="auto")).lower()
    embedding_backend = (
        embedding_backend
        or config.get("retrieval", "embedding_backend", default="auto")
    )
    chunks = list(chunks) if chunks is not None else load_chunks()

    embedder, embedder_info = make_embedder(
        embedding_backend, corpus=[c.text for c in chunks]
    )
    notes: list[str] = []
    if embedder_info.get("downgraded"):
        notes.append(f"embedding downgraded: {embedder_info.get('reason')}")
    if not embedder_info.get("semantic", False):
        notes.append(
            "embedding backend is lexical, not semantic: condition C's retrieval cannot "
            "bridge synonyms in this configuration, which narrows the B-vs-C gap"
        )
    if embedder_info.get("weak_warning"):
        notes.append(str(embedder_info["weak_warning"]))

    persist_dir = Path(persist_dir) if persist_dir is not None else (
        config.ROOT / str(config.get("retrieval", "persist_dir", default="artifacts/chroma_db"))
    )
    index_lock = acquire_index_lock(persist_dir)

    if backend in {"chroma", "auto"}:
        try:
            store = ChromaStore(chunks, embedder, persist_dir)
            store_info = {"backend": store.backend_name, "persist_dir": str(persist_dir)}
        except Exception as exc:  # noqa: BLE001 - fall back, but say so
            if backend == "chroma":
                raise RuntimeError(
                    "retrieval.backend is set to 'chroma' but Chroma could not be "
                    f"initialised: {type(exc).__name__}: {exc}. Set it to 'local' to use "
                    "the in-process numpy index."
                ) from exc
            store = LocalVectorStore(chunks, embedder)
            store_info = {"backend": store.backend_name, "reason": f"chroma unavailable: {type(exc).__name__}"}
            notes.append(f"store downgraded to local: {type(exc).__name__}: {exc}")
    elif backend == "local":
        store = LocalVectorStore(chunks, embedder)
        store_info = {"backend": store.backend_name, "reason": "explicitly configured"}
    else:
        raise ValueError(f"unknown retrieval.backend: {backend!r}")

    return KnowledgeBase(
        store=store,
        embedder_info=embedder_info,
        store_info=store_info,
        chunk_count=len(chunks),
        notes=notes,
        lock_path=index_lock,
    )
