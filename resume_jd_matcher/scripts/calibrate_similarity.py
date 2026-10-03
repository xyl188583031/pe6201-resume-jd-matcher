"""Derive the retrieval similarity calibration from the knowledge base.

Why this exists
---------------
Raw cosine similarity is not on a scale you can threshold at 0.4. A semantic
embedder puts a relevant match around 0.5-0.8; a deterministic hashing fallback
puts it around 0.15-0.25. Thresholding the raw number would make the abstention
rate an artefact of which embedder happened to be installed, not a property of
the system.

So the raw score is rescaled onto [0,1] with two constants:

    score = clip((raw - floor) / (ceiling - floor), 0, 1)

with

    floor   = p10 of "best hit from an IRRELEVANT family"
    ceiling = p90 of "best hit from a RELEVANT family"

Both anchors are deciles, so the scale spans the bulk of each distribution. In
words: at `floor` the retrieval is worse than 90% of wrong-subject retrievals,
and at `ceiling` it is better than 90% of right-subject ones.

An earlier revision paired MEDIAN to MEDIAN, because the p95 of the irrelevant
distribution sat above the relevant median and median-to-median at least
guarantees floor < ceiling. That removed the degenerate-scale error but
introduced a worse one: the two anchors then land on either side of the
overlap's centre, so a large share of retrievals - including roughly half of the
CORRECT ones - clip to 0.0 or 1.0. Measured on the v1 knowledge base with the
lexical embedder, 15 of 20 evaluation cases saturated at 1.000 and two well
retrieved cases clipped to 0.000, forcing false abstentions. Saturation is fatal
for an abstention rule, which only cares about the region near the threshold.

The percentile anchors do NOT remove the underlying overlap, and this script
still reports it: whenever p95(irrelevant) exceeds median(relevant), no monotone
rescaling can turn this score into a reliable confidence component, and the
report has to say so instead of tuning constants until abstention looks good.

Probe queries are JD-shaped ("Job requirements: <skills>. Job description
excerpt: ..."), matching what the pipeline actually sends. An earlier version of
this script used chunk text as the probe and produced a misleading result: all
chunks share boilerplate ("core checklist", "expected"), so same-family and
different-family scores were indistinguishable and the script reported negative
separation. Probing with the real query shape is the difference between
measuring retrieval and measuring boilerplate.

Labels come from the family field already present in the knowledge base. No
evaluation case and no ground-truth label is read, so this cannot be tuned
toward a nicer result on the test set. Re-run it whenever the embedding backend
or the KB changes, and paste the printed values into config.yaml.

    python scripts/calibrate_similarity.py
    python scripts/calibrate_similarity.py --embedding-backend tfidf --write-note
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.retrieval.store import build_knowledge_base  # noqa: E402

JD_BANK = REPO_ROOT / "data" / "synthetic_generator" / "jd_bank.json"
GENERIC_FAMILY = "generic"
SEED = 20260824  # fixed: the calibration must be reproducible


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0,1]. Deterministic, no numpy."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def _family_skill_lists() -> dict[str, list[str]]:
    bank = json.loads(JD_BANK.read_text(encoding="utf-8"))
    display = bank.get("display", {})
    out: dict[str, list[str]] = {}
    for family, spec in bank["families"].items():
        skills = list(spec.get("core_skills", [])) + list(spec.get("nice_to_have", []))
        out[family] = [display.get(s, s) for s in skills]
    return out


def _probe_queries(skills: list[str], titles: list[str], per_family: int) -> list[str]:
    """JD-shaped probes with seeded, reproducible skill subsets."""
    rng = random.Random(SEED)
    queries: list[str] = []
    for i in range(per_family):
        size = rng.randint(5, len(skills))
        subset = rng.sample(skills, size)
        title = titles[i % len(titles)]
        queries.append(
            f"Job requirements: {', '.join(subset)}. "
            f"Job description excerpt: We are hiring a {title} to join our team "
            "and work on production systems."
        )
    return queries


def calibrate(embedding_backend: str | None, per_family: int = 25, top_k: int = 6) -> dict:
    kb = build_knowledge_base(embedding_backend=embedding_backend)
    bank = json.loads(JD_BANK.read_text(encoding="utf-8"))

    relevant: list[float] = []
    irrelevant: list[float] = []
    per_family_report: dict[str, dict[str, float]] = {}
    probes_run = 0

    for family, skills in _family_skill_lists().items():
        titles = bank["families"][family].get("titles", ["Engineer"])
        fam_relevant: list[float] = []
        fam_irrelevant: list[float] = []

        for query in _probe_queries(skills, titles, per_family):
            probes_run += 1
            hits = kb.store.query(query, top_k=top_k)
            rel = [
                h.raw_similarity
                for h in hits
                if h.family in {family, GENERIC_FAMILY}
            ]
            irr = [h.raw_similarity for h in hits if h.family not in {family, GENERIC_FAMILY}]
            if rel:
                fam_relevant.append(max(rel))
            if irr:
                fam_irrelevant.append(max(irr))

        relevant.extend(fam_relevant)
        irrelevant.extend(fam_irrelevant)
        per_family_report[family] = {
            "relevant_median": round(statistics.median(fam_relevant), 4) if fam_relevant else 0.0,
            "irrelevant_median": round(statistics.median(fam_irrelevant), 4) if fam_irrelevant else 0.0,
            "n": len(fam_relevant),
        }

    if not relevant or not irrelevant:
        raise SystemExit(
            "not enough family diversity to calibrate: every probe returned chunks from a "
            "single family. Check that the KB carries `family` metadata."
        )

    irrelevant_sorted = sorted(irrelevant)
    p95_index = min(len(irrelevant_sorted) - 1, int(round(0.95 * (len(irrelevant_sorted) - 1))))
    p95_irrelevant = irrelevant_sorted[p95_index]

    # p10/p90, not median/median. See the module docstring for why: the
    # median pairing clips roughly half of all retrievals - correct ones
    # included - to the ends of the scale, which is what made 15 of 20
    # evaluation cases saturate in the previous revision.
    floor = _percentile(irrelevant, 0.10)
    ceiling = _percentile(relevant, 0.90)

    if ceiling <= floor:
        raise SystemExit(
            f"degenerate calibration: floor={floor:.4f} ceiling={ceiling:.4f}. "
            "This embedder does not separate relevant from irrelevant chunks, so no "
            "similarity scale can be built from it. Fix the embedder, do not widen the "
            "constants."
        )

    return {
        "embedding_backend": kb.embedder_info.get("backend"),
        "store_backend": kb.backend,
        "n_chunks": kb.chunk_count,
        "probe_queries": probes_run,
        "relevant_best": {
            "n": len(relevant),
            "min": round(min(relevant), 4),
            "p10": round(_percentile(relevant, 0.10), 4),
            "median": round(statistics.median(relevant), 4),
            "p90": round(_percentile(relevant, 0.90), 4),
            "max": round(max(relevant), 4),
        },
        "irrelevant_best": {
            "n": len(irrelevant),
            "min": round(min(irrelevant), 4),
            "p10": round(_percentile(irrelevant, 0.10), 4),
            "median": round(statistics.median(irrelevant), 4),
            "p90": round(_percentile(irrelevant, 0.90), 4),
            "max": round(max(irrelevant), 4),
            "p95": round(p95_irrelevant, 4),
        },
        "method": {
            "floor": "p10 of irrelevant-family best hits",
            "ceiling": "p90 of relevant-family best hits",
            "p95_irrelevant_diagnostic": round(p95_irrelevant, 4),
            "overlap_diagnostic": (
                "p95(irrelevant) > median(relevant)"
                if p95_irrelevant > statistics.median(relevant)
                else "distributions are separated at the p95/median cut"
            ),
        },
        "per_family": per_family_report,
        "suggested": {
            "similarity_floor": round(floor, 4),
            "similarity_ceiling": round(ceiling, 4),
        },
        "separation": round(statistics.median(relevant) - statistics.median(irrelevant), 4),
        "separation_over_floor": round(statistics.median(relevant) - floor, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate retrieval similarity scaling")
    parser.add_argument("--embedding-backend", default=None, help="auto | sentence_transformers | tfidf")
    parser.add_argument("--per-family", type=int, default=25, help="probe queries per job family")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--write-note", action="store_true")
    args = parser.parse_args()

    report = calibrate(args.embedding_backend, args.per_family, args.top_k)
    print(json.dumps(report, indent=2))

    suggested = report["suggested"]
    if args.write_note:
        print("\n# paste into config.yaml under retrieval:")
        print(f"  similarity_floor: {suggested['similarity_floor']}")
        print(f"  similarity_ceiling: {suggested['similarity_ceiling']}")

    if float(report["separation"]) <= 0.0:
        print(
            "\nWARNING: relevant and irrelevant similarities overlap - this embedder does not "
            "separate job families. Retrieval quality is weak and any condition-C result "
            "must be reported as such."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
