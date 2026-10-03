"""Embedding backends.

Three options behind one interface, in order of preference:

1. `sentence-transformers/all-MiniLM-L6-v2` - the semantic embedder named in the
   Problem Statement. Needs the package AND a one-off model download.
2. `TfidfCorpusEmbedder` - TF-IDF fitted on the knowledge base, then used to
   transform queries. Deterministic, no network. IDF is what makes this work:
   every chunk in this KB contains boilerplate ("core checklist", "expected",
   "postings"), and IDF drives those shared words toward zero while keeping the
   discriminating ones. An earlier revision of this module used plain signed
   hashing instead, and `scripts/calibrate_similarity.py` showed it could not
   separate job families at all (separation ~0.03, inside the noise band).
3. `HashingEmbedder` - stateless signed hashing. Last resort only, for a
   machine with no scikit-learn. Known to be weak on this corpus.

`auto` tries (1), then (2), then (3). The fallback is never silent: the chosen
backend, the reason, and a `downgraded` flag are recorded on every run and
echoed into the report. A capability downgrade that nobody notices is how an
evaluation result becomes untrustworthy.

Backend (1) is loaded from `retrieval.embedding_model_path` when that directory
holds a usable copy of the model, otherwise by name from the Hugging Face hub.
The local copy exists because the hub downloader's cache directory can be
blocked by a host-level delete guard, which leaves a zero-byte placeholder that
fails only later and degrades the run to a lexical embedder without saying so.

Important limitation: backends (2) and (3) are LEXICAL. Condition C's retrieval
is therefore lexical whenever it falls back, which narrows the B-vs-C gap
precisely for the synonym cases the experiment exists to test. Only backend (1)
makes condition C the semantic condition the Problem Statement describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

HASH_DIM = 1024


def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _stable_hash(token: str) -> int:
    """FNV-1a. Python's builtin hash() is salted per process, which would make a
    'deterministic' fallback non-deterministic across runs."""
    h = 0xCBF29CE484222325
    for byte in token.encode("utf-8"):
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


@dataclass
class TfidfCorpusEmbedder:
    """TF-IDF vocabulary fitted on the knowledge base, reused for queries."""

    corpus: Sequence[str] = ()
    max_features: int = 4096
    ngram_max: int = 2
    name: str = "tfidf-corpus-fitted"
    _vectorizer: object | None = field(default=None, repr=False)

    def _ensure(self) -> None:
        if self._vectorizer is not None:
            return
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, self.ngram_max),
            sublinear_tf=True,
            max_features=self.max_features,
            min_df=1,
        )
        self._vectorizer.fit(list(self.corpus))

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure()
        matrix = self._vectorizer.transform(list(texts))  # type: ignore[attr-defined]
        return _l2_normalise(np.asarray(matrix.todense(), dtype=np.float64))

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.name,
            "corpus_docs": len(self.corpus),
            "needs_download": False,
            "semantic": False,
            "note": "lexical TF-IDF, not a semantic embedder",
        }


@dataclass
class HashingEmbedder:
    """Stateless signed hashing. Weak on this corpus; kept as a last resort."""

    dim: int = HASH_DIM
    use_char_ngrams: bool = True
    name: str = "hashing-fallback"

    def _tokens(self, text: str) -> list[str]:
        lowered = "".join(ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in text)
        words = [w for w in lowered.split() if len(w) > 1]
        grams = list(words)
        if self.use_char_ngrams:
            joined = " ".join(words)
            grams += [joined[i : i + 4] for i in range(0, max(0, len(joined) - 4), 2)]
        return grams

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float64)
        for row, text in enumerate(texts):
            tokens = self._tokens(text)
            if not tokens:
                continue
            counts: dict[int, float] = {}
            for token in tokens:
                h = _stable_hash(token)
                idx = h % self.dim
                counts[idx] = counts.get(idx, 0.0) + (1.0 if (h >> 32) % 2 == 0 else -1.0)
            for idx, value in counts.items():
                matrix[row, idx] = value
        return _l2_normalise(matrix)

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.name,
            "dim": self.dim,
            "needs_download": False,
            "semantic": False,
            "note": "stateless hashing; measured to have near-zero family separation",
        }


@dataclass
class SentenceTransformerEmbedder:
    """Wrapper that loads lazily so importing this module stays cheap.

    `model_path` is an optional local copy of the model. It matters because the
    library's own downloader writes into a shared cache directory and that write
    can be blocked by a host-level delete guard, leaving a zero-byte placeholder
    behind. A poisoned cache then fails late and confusingly - the JSON reader
    chokes on an empty file - and the run silently degrades to a lexical
    embedder, which is exactly the downgrade this project is trying to avoid.
    Loading from a path we control removes that failure mode. Environment
    offline flags are set when a local path is used so no network call is
    attempted at load time.
    """

    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    model_path: str | None = None
    _model: object | None = field(default=None, repr=False)
    name: str = "sentence-transformers"

    def _ensure(self) -> None:
        if self._model is not None:
            return
        import os

        from sentence_transformers import SentenceTransformer

        source = self.model_path or self.model_name
        if self.model_path:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        self._model = SentenceTransformer(source, device="cpu")

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure()
        vectors = self._model.encode(  # type: ignore[attr-defined]
            list(texts), convert_to_numpy=True, show_progress_bar=False
        )
        return _l2_normalise(np.asarray(vectors, dtype=np.float64))

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.name,
            "model": self.model_name,
            "local_path": self.model_path or None,
            "loaded_from": self.model_path or self.model_name,
            "needs_download": not bool(self.model_path),
            "semantic": True,
            "note": "semantic embedder; this is the configuration the Problem Statement assumes",
        }


def resolve_local_model_path(configured: str | None) -> str | None:
    """Absolute path to a local model dir, or None if it is not usable.

    Only treated as usable when both `config.json` and a weights file are
    present and non-empty: a half-written directory is worse than no path,
    because it turns a clean fallback into a late parse error.
    """
    if not configured:
        return None
    from pathlib import Path

    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = _repo_root() / candidate
    if not candidate.is_dir():
        return None
    manifest = candidate / "config.json"
    weights = [
        candidate / "model.safetensors",
        candidate / "pytorch_model.bin",
    ]
    if not manifest.exists() or manifest.stat().st_size == 0:
        return None
    if not any(w.exists() and w.stat().st_size > 0 for w in weights):
        return None
    return str(candidate)


def _repo_root():
    from pathlib import Path

    # src/retrieval/embeddings.py -> repo root
    return Path(__file__).resolve().parents[2]


def make_embedder(
    preference: str, corpus: Sequence[str] | None = None
) -> tuple[object, dict[str, object]]:
    """Return (embedder, info). `info` always states what was chosen and why.

    `corpus` is required by the TF-IDF backend. Without it, that backend is
    skipped rather than faked.
    """
    preference = (preference or "auto").lower()
    corpus = list(corpus or [])

    if preference in {"sentence_transformers", "auto"}:
        local_path: str | None = None
        try:
            from src import config as _config

            local_path = resolve_local_model_path(
                _config.get("retrieval", "embedding_model_path", default=None)
            )
        except Exception:  # noqa: BLE001 - a missing config must not break the fallback
            local_path = None
        candidate = SentenceTransformerEmbedder(model_path=local_path)
        try:
            candidate.encode(["warmup probe"])
            info = candidate.describe()
            info["reason"] = (
                f"sentence-transformers loaded from the local copy at {local_path}"
                if local_path
                else "sentence-transformers loaded successfully"
            )
            return candidate, info
        except Exception as exc:  # noqa: BLE001 - any failure means fall back
            if preference == "sentence_transformers":
                raise RuntimeError(
                    "retrieval.embedding_backend is set to sentence_transformers but it "
                    f"could not be loaded: {type(exc).__name__}: {exc}. "
                    "Use 'tfidf' (corpus-fitted TF-IDF fallback) to run without a model download."
                ) from exc
            st_reason = (
                f"sentence-transformers unavailable ({type(exc).__name__}: {exc}); "
                "used corpus-fitted TF-IDF instead"
            )
    else:
        st_reason = "not requested"

    if preference in {"sentence_transformers", "tfidf", "auto"} and corpus:
        try:
            fallback = TfidfCorpusEmbedder(corpus=corpus)
            fallback.encode(["warmup probe"])  # force the fit now, not mid-run
            info = fallback.describe()
            info["reason"] = st_reason
            info["downgraded"] = preference != "tfidf"
            return fallback, info
        except Exception as exc:  # noqa: BLE001
            if preference == "tfidf":
                raise RuntimeError(
                    f"TF-IDF fallback requested but failed: {type(exc).__name__}: {exc}"
                ) from exc
            hash_reason = f"TF-IDF fallback failed ({type(exc).__name__}: {exc})"
    else:
        hash_reason = "no corpus supplied for the TF-IDF backend"

    fallback = HashingEmbedder()
    info = fallback.describe()
    info["reason"] = hash_reason
    info["downgraded"] = True
    info["weak_warning"] = (
        "hashing vectors were measured not to separate job families on this corpus; "
        "retrieval-dependent results are unreliable in this configuration"
    )
    return fallback, info
