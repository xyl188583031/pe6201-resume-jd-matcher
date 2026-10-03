"""Validate and build the RAG knowledge base.

Run:  python -m data.knowledge_base.build_kb
      python -m data.knowledge_base.build_kb --query "pytorch model deployment"

Validation is strict on purpose. The Problem Statement commits to "~50 short
text chunks (<500 chars each)". A chunk that drifts over that limit is a broken
commitment, not a rounding error, so this fails loudly instead of truncating.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.retrieval.store import build_knowledge_base, load_chunks  # noqa: E402

DEFAULT_CHUNKS = Path(__file__).resolve().parent / "kb_chunks.json"


def validate(path: Path) -> dict[str, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["chunks"] if isinstance(raw, dict) and "chunks" in raw else raw
    max_chars = int(config.get("retrieval", "max_chunk_chars", default=500))
    min_chars = int(config.get("retrieval", "min_chunk_chars", default=40))

    problems: list[str] = []
    ids: set[str] = set()
    family_counts: dict[str, int] = {}

    for i, item in enumerate(items):
        cid = str(item.get("id") or f"<missing id at index {i}>")
        text = str(item.get("text", ""))
        if cid in ids:
            problems.append(f"duplicate chunk id: {cid}")
        ids.add(cid)
        if len(text) > max_chars:
            problems.append(f"{cid}: {len(text)} chars exceeds max_chars={max_chars}")
        if len(text) < min_chars:
            problems.append(f"{cid}: only {len(text)} chars, below min_chars={min_chars}")
        if not item.get("source"):
            problems.append(f"{cid}: missing `source` (retrieval provenance would be blank)")
        family = str(item.get("family", "generic"))
        family_counts[family] = family_counts.get(family, 0) + 1

    if problems:
        print(f"FAIL  {len(problems)} problem(s) in {path}")
        for problem in problems[:20]:
            print(f"  - {problem}")
        raise SystemExit(1)

    print(f"OK    {len(items)} chunk(s) validated against max_chars={max_chars}")
    for family, count in sorted(family_counts.items()):
        print(f"      {family:<24} {count}")
    lengths = sorted(len(str(i.get("text", ""))) for i in items)
    print(
        f"      chunk length: min {lengths[0]}, median {lengths[len(lengths) // 2]}, "
        f"max {lengths[-1]}"
    )
    return family_counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and build the RAG knowledge base")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--query", type=str, default=None, help="run a probe query after building")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--backend", default=None, help="auto | chroma | local")
    parser.add_argument("--embedding-backend", default=None, help="auto | sentence_transformers | tfidf")
    args = parser.parse_args()

    validate(args.chunks)

    # load_chunks reads the configured path; keep the two in step.
    configured = config.path("knowledge_base")
    if configured.resolve() != args.chunks.resolve():
        print(f"NOTE  config.knowledge_base is {configured}, validating {args.chunks}")

    kb = build_knowledge_base(backend=args.backend, embedding_backend=args.embedding_backend)
    print("\nstore:", json.dumps(kb.describe(), indent=2, ensure_ascii=False))

    if args.query:
        result = kb.retrieve(args.query, top_k=args.top_k)
        print(f"\nprobe query: {args.query!r}")
        for hit in result.hits:
            print(f"  {hit.score:.3f}  {hit.chunk_id:<20} {hit.text[:70]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
