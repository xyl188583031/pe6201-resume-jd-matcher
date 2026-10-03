"""Re-derive a run's metrics/report artefacts from its log, with no API calls.

Purpose
-------
`artifacts/<out-dir>/` holds four files: `runs.jsonl` (the raw record, the only
irreplaceable one), `metrics.csv`, `case_scores.csv` and `report.md` (all three
derived). Two of the scoring rules changed after the delivered run was executed:

  * `CaseScore.passed` now also requires that the case was not declined, so a
    case the system refused to answer is no longer credited as a pass;
  * `write_metrics_csv` now receives the real pass-bar fraction instead of 0.0,
    so `meets_pass_bar` is no longer a constant 1.

Rather than spend another live run (and change the records, because temperature
is 0.1), this script rebuilds the three derived files from `runs.jsonl` using the
current code. The record is untouched; only the arithmetic over it moves.

Usage
-----
    python scripts/rescore_run.py --artifacts artifacts/kbv2_final
    python scripts/rescore_run.py --artifacts artifacts/kbv2_repeat --dry-run
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
from src.evaluation import report as report_mod  # noqa: E402
from src.evaluation.metrics import (  # noqa: E402
    build_condition_metrics,
    load_ground_truth,
    score_run,
)
from src.pipeline.runner import CONDITION_LABELS  # noqa: E402


def _read_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _aggregate_cost(records: list[dict]) -> dict:
    calls = prompt = completion = 0
    cost = 0.0
    for rec in records:
        usage = rec.get("usage") or {}
        calls += int(usage.get("calls") or 0)
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
        cost += float(usage.get("est_cost_usd") or 0.0)
    return {
        "mode": records[0].get("mode", "") if records else "",
        "model": records[0].get("model", "") if records else "",
        "calls": calls,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "est_cost_usd": round(cost, 6),
        "note": "cost is an ESTIMATE from the price table in config.yaml, not an invoice",
    }


def _kb_descriptor(out_dir: Path, records: list[dict]) -> dict:
    """Retrieval descriptor, read from the run's own artefacts.

    This must NOT build the knowledge base. Building it deletes and recreates the
    vector collection, so a tool whose only job is to re-derive a table would
    mutate state that a concurrently running evaluation is reading - which is
    exactly how a repeat run lost all 20 of its condition-C cases. The run now
    writes `kb_descriptor.json`; this reads it.
    """
    if not any(r.get("retrieved_chunk_ids") for r in records):
        return {"note": "condition C not run; no retrieval"}
    for name in ("kb_descriptor.json", "_kb_descriptor.json"):
        path = out_dir / name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                return {"note": f"kb descriptor unreadable ({type(exc).__name__})"}
    return {
        "note": (
            "kb descriptor not written by this run (it predates kb_descriptor.json); "
            "re-derive with scripts/calibrate_similarity.py rather than rebuilding here"
        )
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", default=str(config.path("artifacts")),
                    help="directory holding runs.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="print only, write nothing")
    args = ap.parse_args()

    out_dir = Path(args.artifacts)
    runs_path = out_dir / "runs.jsonl"
    if not runs_path.exists():
        print(f"no runs.jsonl in {out_dir}")
        return 2

    records = _read_records(runs_path)
    if not records:
        print(f"runs.jsonl in {out_dir} is empty")
        return 2

    gt_path = config.path("ground_truth")
    ground_truth = load_ground_truth(gt_path)
    eval_cfg = config.evaluate_config()
    confidence_cfg = config.ConfidenceConfig.load()

    conditions = sorted({r.get("condition") for r in records if r.get("condition")})
    metrics = []
    all_scores = []
    for condition in conditions:
        subset = [r for r in records if r.get("condition") == condition]
        scores = score_run(subset, ground_truth)
        all_scores.extend(scores)
        metrics.append(
            build_condition_metrics(
                condition,
                CONDITION_LABELS.get(condition, condition),
                scores,
                pass_bar_fraction=eval_cfg["pass_bar_fraction"],
            )
        )

    n_cases = max((m.n_cases for m in metrics), default=0)
    minimum = int(round(eval_cfg["pass_bar_fraction"] * n_cases))
    ctx = report_mod.RunContext(
        run_id=records[0].get("run_id", "unknown"),
        mode=records[0].get("mode", "unknown"),
        model=records[0].get("model", "unknown"),
        n_cases=n_cases,
        pass_bar_fraction=eval_cfg["pass_bar_fraction"],
        abstention_ceiling=eval_cfg["abstention_rate_ceiling"],
        threshold=confidence_cfg.threshold,
        kb=_kb_descriptor(out_dir, records),
        cost=_aggregate_cost(records),
        conditions_run=conditions,
        started_at="",
        extra_notes=[
            "Rebuilt from runs.jsonl by scripts/rescore_run.py, after CaseScore.passed "
            "gained its `not abstained` clause and metrics.csv stopped hard-coding a "
            "zero-width pass bar. The record itself was not re-collected."
        ],
    )

    print(f"run        : {ctx.run_id}  mode={ctx.mode}  model={ctx.model}")
    print(f"pass bar   : {minimum}/{n_cases}")
    for m in metrics:
        row = m.as_row(ctx.pass_bar_fraction, ctx.abstention_ceiling)
        print(
            f"  {m.condition}: passed {row['passed_bar']:>6}  meets={row['meets_pass_bar']}  "
            f"coverage {row['complete_coverage']:>5}  clean {row['zero_fabrication']:>5}  "
            f"prefill {row['prefill_all_match']:>5}  abstain {row['abstained']:>5}"
        )

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    report_mod.write_metrics_csv(
        metrics,
        out_dir / "metrics.csv",
        pass_bar_fraction=ctx.pass_bar_fraction,
        abstention_ceiling=ctx.abstention_ceiling,
    )
    report_mod.write_case_scores_csv(all_scores, out_dir / "case_scores.csv")
    report_mod.write_report(
        report_mod.build_report(metrics, all_scores, ctx),
        out_dir / "report.md",
    )
    print(f"\nrewrote metrics.csv, case_scores.csv and report.md in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
