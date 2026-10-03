"""Write a run's `kb_descriptor.json` from the live code path, without an index rebuild.

Why this exists
---------------
`eval/run_eval.py` writes `kb_descriptor.json` next to the run log. The delivered
run `run-20260925-123027` predates that behaviour, so its artefact directory has
none, and `scripts/rescore_run.py` therefore cannot describe the retrieval
configuration it actually ran under - it falls back to a note, and `report.md`
then prints "embedding backend in force: None (semantic: False)" plus a
**lexical** caveat. That is false: the run's console shows
`retrieval : chroma + sentence-transformers`.

This script rebuilds *only the descriptor*, by calling the same functions
`build_knowledge_base` calls for its metadata (`load_chunks`, `make_embedder`),
and re-uses that function's note logic. It does **not** construct `ChromaStore`,
so the vector collection is neither read nor rewritten - the whole point of the
index-lock work was to stop metadata tools from mutating the index.

It records its own provenance in `notes` so a reader knows the descriptor was
reconstructed rather than emitted by the run itself.

Usage
-----
    python scripts/write_kb_descriptor.py \
        --out artifacts/kbv2_final/kb_descriptor.json \
        --persist-dir artifacts/chroma_db \
        --note "reconstructed: the run predates kb_descriptor.json"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.retrieval.embeddings import make_embedder  # noqa: E402
from src.retrieval.store import Chunk, load_chunks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="path to write kb_descriptor.json")
    ap.add_argument("--persist-dir", default=None,
                    help="the index location the run actually used (informational)")
    ap.add_argument("--note", action="append", default=[],
                    help="provenance note, repeatable")
    args = ap.parse_args()

    chunks: list[Chunk] = load_chunks()
    chunk_count = len(chunks)

    embedding_backend = config.get("retrieval", "embedding_backend", default="auto")
    embedder, embedder_info = make_embedder(
        embedding_backend, corpus=[c.text for c in chunks]
    )

    # Mirror build_knowledge_base's note logic exactly, so the descriptor this
    # writes is the descriptor that function would have written.
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
    notes.extend(args.note)

    persist_dir = args.persist_dir or str(
        config.ROOT / str(config.get("retrieval", "persist_dir", default="artifacts/chroma_db"))
    )

    descriptor = {
        "chunks": chunk_count,
        "store": {"backend": "chroma", "persist_dir": persist_dir},
        "embedder": embedder_info,
        "notes": notes,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(descriptor, indent=1, default=str), encoding="utf-8")

    print(f"wrote {out}")
    print(f"  chunks     : {chunk_count}")
    print(f"  embedder   : {embedder_info.get('backend')} (semantic={embedder_info.get('semantic')})")
    print(f"  persist_dir: {persist_dir}")
    for n in notes:
        print(f"  note       : {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
