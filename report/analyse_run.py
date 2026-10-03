"""Everything the final report needs, recomputed from the run log.

Reads artifacts/runs.jsonl + data/cases/ground_truth.csv and prints a single
block of numbers. Every figure the report quotes should be traceable to a line
this script printed, so the report can be re-checked without re-running the API.

    python report/analyse_run.py                 # uses artifacts/
    python report/analyse_run.py --run-id <id>   # a specific run in the log
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "resume_jd_matcher"
sys.path.insert(0, str(REPO))

from src.evaluation.metrics import load_ground_truth, score_case  # noqa: E402
from src.taxonomy import canonicalise, normalise_skill  # noqa: E402


def load_run(path: Path, run_id: str | None) -> tuple[str, list[dict]]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        raise SystemExit(f"no records in {path}")
    rid = run_id or rows[-1]["run_id"]
    selected = [r for r in rows if r.get("run_id") == rid]
    if not selected:
        raise SystemExit(f"run {rid} not found in {path}")
    return rid, selected


def money(usd: float) -> str:
    return f"${usd:.4f}" if usd < 1 else f"${usd:,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    art = Path(args.artifacts)
    run_id, records = load_run(art / "runs.jsonl", args.run_id)
    gt = load_ground_truth(REPO / "data" / "cases" / "ground_truth.csv")

    mode = records[0].get("mode")
    model = records[0].get("model")
    print("=" * 78)
    print(f"RUN {run_id}")
    print(f"mode={mode}  model={model}  records={len(records)}")
    print("=" * 78)

    by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cond[r["condition"]].append(r)

    # ---------------------------------------------------------------- headline
    print("\n## 1. Headline, counts first\n")
    header = f"{'cond':<5}{'cases':>6}{'passed':>8}{'coverage':>10}{'clean':>8}{'prefill':>9}{'abstain':>9}{'meanconf':>10}"
    print(header)
    print("-" * len(header))
    summary: dict[str, dict] = {}
    for cond in sorted(by_cond):
        scores = [score_case(r, gt[r["case_id"]]) for r in by_cond[cond] if r["case_id"] in gt]
        n = len(scores)
        passed = sum(1 for s in scores if s.passed)
        cov = sum(1 for s in scores if s.complete_coverage)
        clean = sum(1 for s in scores if s.zero_fabrication)
        pre = sum(1 for s in scores if s.prefill_all_match)
        abst = sum(1 for s in scores if s.abstained)
        mc = sum(s.confidence for s in scores) / n if n else 0.0
        summary[cond] = dict(n=n, passed=passed, cov=cov, clean=clean, pre=pre, abst=abst,
                             scores=scores)
        print(f"{cond:<5}{n:>6}{passed:>5}/{n:<2}{cov:>7}/{n:<2}{clean:>5}/{n:<2}"
              f"{pre:>6}/{n:<2}{abst:>6}/{n:<2}{mc:>10.3f}")

    # ------------------------------------------------------------- abstention
    print("\n## 2. Abstention, both numbers (Watch-outs p.3)\n")
    for cond in sorted(summary):
        s = summary[cond]["scores"]
        hard = [x for x in s if x.hard_case]
        easy = [x for x in s if not x.hard_case]
        print(f"  {cond}: abstained {sum(1 for x in s if x.abstained)}/{len(s)}"
              f"   on hard {sum(1 for x in hard if x.abstained)}/{len(hard)}"
              f"   false abstentions (easy, abstained) {sum(1 for x in easy if x.abstained)}/{len(easy)}"
              f"   should_abstain cases {sum(1 for x in s if x.should_abstain)}")

    # --------------------------------------------------------------- failures
    print("\n## 3. Failures, named\n")
    for cond in sorted(summary):
        fails = [x for x in summary[cond]["scores"] if not x.passed]
        print(f"  {cond}: {len(fails)} not passing")
        for f in fails:
            why = []
            if not f.zero_fabrication:
                why.append(f"fabricated={f.fabricated}")
            if not f.prefill_all_match:
                bad = [k for k, v in f.prefill_match.items() if not v]
                why.append(f"prefill miss={bad}")
            if f.abstained:
                why.append("abstained")
            if f.errors:
                why.append(f"errors={f.errors[:1]}")
            print(f"      {f.case_id:<48} {'; '.join(why)}")

    # ------------------------------------------------------------------ detail
    print("\n## 4. Per-field prefill exact match\n")
    for cond in sorted(summary):
        s = summary[cond]["scores"]
        row = {k: sum(1 for x in s if x.prefill_match.get(k)) for k in
               ("full_name", "email", "education_school", "top_skills")}
        print(f"  {cond}: " + "  ".join(f"{k}={v}/{len(s)}" for k, v in row.items()))

    # -------------------------------------------------------------- by family
    print("\n## 5. Passed by job family\n")
    fams = sorted({v.job_family for v in gt.values()})
    print(f"  {'cond':<5}" + "".join(f"{f[:18]:>20}" for f in fams))
    for cond in sorted(summary):
        cells = []
        for fam in fams:
            xs = [x for x in summary[cond]["scores"] if x.job_family == fam]
            cells.append(f"{sum(1 for x in xs if x.passed)}/{len(xs)}")
        print(f"  {cond:<5}" + "".join(f"{c:>20}" for c in cells))

    # -------------------------------------------------------------------- cost
    print("\n## 6. Cost and latency (live only)\n")
    for cond in sorted(summary):
        rows = by_cond[cond]
        pt = sum(int((r.get("usage") or {}).get("prompt_tokens", 0)) for r in rows)
        ct = sum(int((r.get("usage") or {}).get("completion_tokens", 0)) for r in rows)
        calls = sum(int((r.get("usage") or {}).get("calls", 0)) for r in rows)
        cost = sum(float((r.get("usage") or {}).get("est_cost_usd", 0.0)) for r in rows)
        lat = [int(r.get("latency_ms") or 0) for r in rows]
        lat_sorted = sorted(lat)
        med = lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0
        n = len(rows)
        print(f"  {cond}: calls={calls}  in={pt:,}  out={ct:,}  est_cost={money(cost)}"
              f"  per_case={money(cost / n if n else 0)}"
              f"  latency ms median={med} max={max(lat) if lat else 0}")

    # ------------------------------------- cost per successful task (Class 5/C2)
    print("\n## 7. Cost per SUCCESSFUL task (Class5/C2 p.21)\n")
    for cond in sorted(summary):
        rows = by_cond[cond]
        cost = sum(float((r.get("usage") or {}).get("est_cost_usd", 0.0)) for r in rows)
        passed = summary[cond]["passed"]
        n = summary[cond]["n"]
        per_pass = (cost / passed) if passed else float("nan")
        print(f"  {cond}: total {money(cost)} / {passed} passed = "
              f"{money(per_pass) if passed else 'n/a'} per successful task"
              f"   (passed {passed}/{n})")

    # ------------------------------------------------------ coverage movement
    print("\n## 8. Coverage: mean fraction of JD requirements captured\n")
    for cond in sorted(summary):
        s = summary[cond]["scores"]
        mean_cov = sum(x.coverage for x in s) / len(s) if s else 0.0
        print(f"  {cond}: mean coverage {mean_cov:.3f}")

    # ------------------------------------------------------------- retrieval
    if "C" in by_cond:
        print("\n## 9. Condition C retrieval\n")
        rows = by_cond["C"]
        sims = [float(r.get("retrieval_similarity") or 0.0) for r in rows]
        chunk_counts = [len(r.get("retrieved_chunk_ids") or []) for r in rows]
        ids = Counter(cid for r in rows for cid in (r.get("retrieved_chunk_ids") or []))
        print(f"  top-1 similarity: min {min(sims):.3f} median {sorted(sims)[len(sims)//2]:.3f}"
              f" max {max(sims):.3f}")
        print(f"  chunks per case: {Counter(chunk_counts).most_common()}")
        print(f"  distinct chunks retrieved: {len(ids)}")
        print("  top 8: " + ", ".join(f"{k}×{v}" for k, v in ids.most_common(8)))

    # ------------------------------------------------- silent-failure signal
    print("\n## 10. Guard activity (notes now persisted) and errors\n")
    noted = Counter()
    for r in records:
        for n in (r.get("notes") or []):
            key = n.split(":")[0][:70]
            noted[key] += 1
    for k, v in noted.most_common(12):
        print(f"  {v:>3}× {k}")
    errs = [(r["condition"], r["case_id"], e) for r in records for e in (r.get("errors") or [])]
    print(f"  errors: {len(errs)}")
    for c, cid, e in errs[:10]:
        print(f"     {c} {cid}: {e[:110]}")

    # ------------------------------------------------- guard: caught vs shown
    # `claimed_items` is the post-guard value the scorer counts; `stripped_claims`
    # is what the guard removed before it was ever shown. Keeping them apart is
    # what makes "the model proposed a fabrication" distinguishable from "the
    # system displayed one" - the two are not the same result and the report
    # must not blur them.
    print("\n## 11. Fabrication guard: proposed vs displayed\n")
    for cond in sorted(summary):
        rows = by_cond[cond]
        stripped = [s for r in rows for s in (r.get("stripped_claims") or [])]
        shown = [i for s in summary[cond]["scores"] for i in s.fabricated]
        print(f"  {cond}: model-proposed-and-stripped={len(stripped)}"
              f"   displayed-as-fact={len(shown)}")
        if stripped:
            for item in Counter(stripped).most_common(6):
                print(f"        stripped: {item[0]} ×{item[1]}")
        if shown:
            for item in Counter(shown).most_common(6):
                print(f"        DISPLAYED: {item[0]} ×{item[1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
