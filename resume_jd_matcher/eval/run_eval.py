"""Run the evaluation: 3 conditions x N cases, then score and report.

    python eval/run_eval.py                          # offline plumbing check, 20 cases
    python eval/run_eval.py --live                   # real OpenRouter calls
    python eval/run_eval.py --n-cases 40 --live       # the "or get to 40" option
    python eval/run_eval.py --conditions A            # baseline only

Design notes that matter for whether the numbers mean anything
-------------------------------------------------------------
* The pipeline receives ONLY `resume_text` and `jd_text`. Job family, variant,
  the required-skill list and `should_abstain` all live in `cases.json` and are
  never passed in. They are ground-truth labels; feeding any of them to the
  system would be label leakage and would inflate every metric.
* Ground truth is read from `data/cases/ground_truth.csv`, which was written by
  the generator BEFORE this script ran. Nothing here computes a label.
* Runs are appended to `artifacts/runs.jsonl`. Use `--fresh` to start a new log.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.config import ConfidenceConfig  # noqa: E402
from src.evaluation import report as report_mod  # noqa: E402
from src.evaluation.metrics import (  # noqa: E402
    build_condition_metrics,
    load_ground_truth,
    score_run,
)
from src.evaluation.timing import evaluate_timing, load_timers  # noqa: E402
from src.llm.client import OpenRouterClient  # noqa: E402
from src.logging_utils import RunLogger  # noqa: E402
from src.pipeline.runner import CONDITION_LABELS, run_case  # noqa: E402
from src.retrieval.store import build_knowledge_base  # noqa: E402


def load_cases(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"cases not found at {path}. Run:\n"
            "  python -m data.synthetic_generator.generate_cases"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"] if isinstance(payload, dict) and "cases" in payload else payload
    return cases[:limit] if limit else cases


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID still exists.

    `tasklist` is invoked as bytes and decoded leniently: on a non-English
    Windows the output is in the console code page, and asking subprocess for
    `text=True` raises inside its reader thread, which silently yields an empty
    stdout and makes every PID look dead. That failure mode is worse than no
    check at all, because it turns the guard off while appearing to work.
    """
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess

            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                timeout=15,
            )
            text = (out.stdout or b"").decode("utf-8", errors="replace")
            if not text:
                text = (out.stdout or b"").decode("mbcs", errors="replace")
            return str(pid) in text
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001 - liveness is best-effort, never fatal
        return False


def acquire_run_lock(out_dir: Path) -> None:
    """Refuse to start a second evaluation against the same artifacts directory.

    Two concurrent runs share `runs.jsonl` and the Chroma collection, and the
    damage is silent rather than loud: `--fresh` truncates the other run's log,
    and rebuilding the store makes the other run's collection vanish mid-flight.
    The result is a metrics table computed from a mixture of two runs, each
    scored against the other's `run_id`. That actually happened while producing
    this report, so the guard is a file lock rather than a comment in a README.
    """
    lock = out_dir / ".run.lock"
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            info = {}
        pid = int(info.get("pid") or 0)
        if pid and _pid_alive(pid):
            raise SystemExit(
                f"REFUSING TO START: another evaluation is already running "
                f"(pid {pid}, started {info.get('started_at')}).\n"
                f"A second run would corrupt {out_dir / 'runs.jsonl'} and the "
                f"vector store, so the numbers would be uninterpretable.\n"
                f"If that process is gone, delete {lock} and retry."
            )
        print(f"NOTE  clearing a stale run lock (pid {pid} is gone)")
    lock.write_text(
        json.dumps(
            {"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        ),
        encoding="utf-8",
    )

    def _release() -> None:
        # Cleanup must never mask the run's own result. Removing a file can be
        # intercepted by the host environment (a delete guard raised SystemExit
        # here once, after a complete and correct run), and an exception inside
        # an atexit hook prints a traceback that looks like a failure.
        try:
            lock.unlink(missing_ok=True)
        except BaseException:  # noqa: BLE001
            pass

    atexit.register(_release)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the A/B/C evaluation")
    parser.add_argument("--n-cases", type=int, default=None, choices=[20, 40])
    parser.add_argument("--conditions", default=None, help="comma separated, e.g. A,B,C")
    parser.add_argument("--live", action="store_true", help="force live API calls (needs a key)")
    parser.add_argument("--offline", action="store_true", help="force the deterministic stub")
    parser.add_argument("--api-key", default=None, help="overrides OPENROUTER_API_KEY")
    parser.add_argument("--embedding-backend", default=None, help="auto | sentence_transformers | tfidf")
    parser.add_argument("--store-backend", default=None, help="auto | chroma | local")
    parser.add_argument("--limit", type=int, default=None, help="debug: only the first N cases")
    parser.add_argument("--fresh", action="store_true", help="truncate runs.jsonl first")
    parser.add_argument("--out-dir", default=None, help="defaults to artifacts/")
    args = parser.parse_args()

    if args.live and args.offline:
        raise SystemExit("--live and --offline are mutually exclusive")

    cfg = ConfidenceConfig.load()
    eval_cfg = config.evaluate_config()
    n_cases = args.n_cases or eval_cfg["n_cases"]
    conditions = (
        [c.strip().upper() for c in args.conditions.split(",")]
        if args.conditions
        else list(eval_cfg["conditions"])
    )

    cases = load_cases(config.path("cases"), args.limit)
    if args.limit is None and len(cases) != n_cases:
        print(
            f"NOTE  config wants {n_cases} cases but cases.json holds {len(cases)}. "
            "Regenerate with --n-cases to change the set."
        )
    ground_truth = load_ground_truth(config.path("ground_truth"))

    out_dir = Path(args.out_dir) if args.out_dir else config.path("artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    acquire_run_lock(out_dir)

    run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}"
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    client = OpenRouterClient(
        api_key=args.api_key,
        force_offline=True if args.offline else (False if args.live else None),
    )

    kb = None
    if "C" in conditions:
        # The index belongs to this run's out-dir. A single shared path let a
        # second process (including a tool that only wanted a description of the
        # index) delete the collection this run was querying, which surfaced as
        # 20 `NotFoundError`s on condition C and looked like a model failure.
        kb = build_knowledge_base(
            backend=args.store_backend,
            embedding_backend=args.embedding_backend,
            persist_dir=out_dir / "chroma_db",
        )

    mode = "offline_stub" if client.offline else "live_api"
    print(f"run id      : {run_id}")
    print(f"mode        : {mode}")
    print(f"model       : {'offline-deterministic-stub' if client.offline else client.cfg.model}")
    print(f"conditions  : {', '.join(conditions)}")
    print(f"cases       : {len(cases)}")
    if kb is not None:
        print(f"retrieval   : {kb.backend} + {kb.embedder_info.get('backend')}")
        for note in kb.notes:
            print(f"              note: {note}")
    if client.offline:
        print(
            "\nWARNING: offline mode. Condition A is real; B and C are served by a deterministic\n"
            "         rule-based stub, so this run validates the pipeline and NOT model behaviour.\n"
            "         Set OPENROUTER_API_KEY (or pass --live) for results.\n"
        )

    logger = RunLogger(path=out_dir / "runs.jsonl", append=not args.fresh)
    form_schema = json.loads(config.path("form_schema").read_text(encoding="utf-8")) if config.path("form_schema").exists() else None

    all_scores = []
    metrics = []

    with logger:
        for condition in conditions:
            print(f"\n--- condition {condition} ({CONDITION_LABELS.get(condition, '?')}) ---")
            for index, case in enumerate(cases, start=1):
                try:
                    result = run_case(
                        case_id=case["case_id"],
                        resume_text=case["resume_text"],
                        jd_text=case["jd_text"],
                        condition=condition,
                        job_family=case["job_family"],
                        variant=case["variant"],
                        client=client,
                        kb=kb,
                        cfg=cfg,
                        form_schema=form_schema,
                    )
                except Exception as exc:  # noqa: BLE001 - a crash is a failed case, not a dead run
                    from src.logging_utils import RunRecord

                    record = RunRecord(
                        run_id=run_id,
                        condition=condition,
                        case_id=case["case_id"],
                        job_family=case["job_family"],
                        variant=case["variant"],
                        mode=mode,
                        model="offline-deterministic-stub" if client.offline else client.cfg.model,
                        abstained=True,
                        abstention_reason=f"pipeline error: {type(exc).__name__}: {exc}",
                        errors=[f"{type(exc).__name__}: {exc}"],
                    )
                    logger.log(record)
                    print(f"  [{index:>2}/{len(cases)}] {case['case_id']:<46} ERROR {type(exc).__name__}")
                    continue

                logger.log(result.to_record(run_id, client.cfg.model))
                flag = "ABSTAIN" if result.abstained else "answer "
                print(
                    f"  [{index:>2}/{len(cases)}] {case['case_id']:<46} {flag} "
                    f"conf {float(result.assessment.combined):.2f} "
                    f"score {result.match_score:>3} "
                    f"chunks {len(result.retrieved_chunk_ids)}"
                )

    records = [r for r in logger.read_all() if r.get("run_id") == run_id]
    for condition in conditions:
        condition_records = [r for r in records if r.get("condition") == condition]
        scores = score_run(condition_records, ground_truth)
        m = build_condition_metrics(
            condition,
            CONDITION_LABELS.get(condition, condition),
            scores,
            pass_bar_fraction=eval_cfg["pass_bar_fraction"],
        )
        metrics.append(m)
        all_scores.extend(scores)

    # ---- outputs
    report_mod.write_metrics_csv(
        metrics,
        out_dir / "metrics.csv",
        pass_bar_fraction=eval_cfg["pass_bar_fraction"],
        abstention_ceiling=eval_cfg["abstention_rate_ceiling"],
    )
    report_mod.write_case_scores_csv(all_scores, out_dir / "case_scores.csv")

    timing_cfg = config.timing_config()
    timing_result = None
    if timing_cfg["enabled"]:
        timing_result = evaluate_timing(
            load_timers(config.ROOT / timing_cfg["timers_file"]),
            min_timers=timing_cfg["min_timers"],
            target_reduction=timing_cfg["target_reduction"],
        )

    kb_desc = kb.describe() if kb is not None else {"note": "condition C not run; no retrieval"}
    # Persist the descriptor next to the run log, so a later reader can describe
    # the run without rebuilding the index (which would be a second writer).
    (out_dir / "kb_descriptor.json").write_text(
        json.dumps(kb_desc, indent=1, default=str), encoding="utf-8"
    )


    ctx = report_mod.RunContext(
        run_id=run_id,
        mode=mode,
        model="offline-deterministic-stub" if client.offline else client.cfg.model,
        n_cases=len(cases),
        pass_bar_fraction=eval_cfg["pass_bar_fraction"],
        abstention_ceiling=eval_cfg["abstention_rate_ceiling"],
        threshold=cfg.threshold,
        kb=kb_desc,
        cost=client.cost_summary(),
        conditions_run=conditions,
        started_at=started_at,
    )
    report_mod.write_report(
        report_mod.build_report(metrics, all_scores, ctx, timing=timing_result),
        out_dir / "report.md",
    )

    # ---- console summary, counts first
    minimum = int(round(eval_cfg["pass_bar_fraction"] * len(cases)))
    print("\n" + "=" * 78)
    print(f"{'condition':<28}{'passed':>12}{'coverage':>12}{'clean':>10}{'prefill':>10}{'abstain':>10}")
    print("-" * 78)
    for m in metrics:
        print(
            f"{m.condition + ' - ' + m.label:<28}"
            f"{m.counts['passed']:>5}/{m.n_cases:<6}"
            f"{m.counts['complete_coverage']:>5}/{m.n_cases:<6}"
            f"{m.counts['zero_fabrication']:>4}/{m.n_cases:<5}"
            f"{m.counts['prefill_all_match']:>4}/{m.n_cases:<5}"
            f"{m.counts['abstained']:>4}/{m.n_cases:<5}"
        )
    print("-" * 78)
    print(f"slice bar = {minimum}/{len(cases)} cases   ('coverage' = named + implied requirements)")
    for m in metrics:
        hard_n = m.denominators.get("abstained_on_hard", 0)
        print(
            f"  {m.condition}: abstained on hard cases {m.counts['abstained_on_hard']}/{hard_n}, "
            f"false abstentions {m.counts['abstained_on_easy']}/{m.denominators.get('abstained_on_easy', 0)}, "
            f"fabrications {m.counts['total_fabrications']}"
        )
    print(f"\nwrote {out_dir / 'runs.jsonl'}")
    print(f"wrote {out_dir / 'metrics.csv'}")
    print(f"wrote {out_dir / 'case_scores.csv'}")
    print(f"wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
