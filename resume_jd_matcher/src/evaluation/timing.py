"""The 30% time-saving metric, gated so it cannot be reported dishonestly.

Instructor feedback (Milestone 1, OUTCOME METRICS):

    "The 30% time saving has one timer and it is you both times - you will be
     faster the second run because you know the answers. Find three people or
     drop it. A/B/C on fabrication and skill coverage carries the claim alone."

That is a correct objection and it is a measurement-design problem, not a
presentation problem. A single person timing themselves twice cannot separate
"the tool helped" from "I had already seen the task". So:

* The metric is OFF by default (`timing.enabled: false`).
* When enabled it returns `reportable=False` unless at least
  `min_independent_timers` DISTINCT timers have recorded BOTH phases for the
  same case. Below that, it produces no number at all - not a preliminary one,
  not a directional one.
* Each timer's first exposure is recorded, so a timer who did the baseline run
  after the assisted run can be flagged as order-contaminated.
* The reduce-by-30%-or-not verdict is stated as a count over cases, consistent
  with the rest of the evaluation.

Timers file format (CSV): timer_id, case_id, phase, minutes, first_exposure

    phase          : baseline | assisted
    first_exposure : baseline_first | assisted_first
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PHASES = ("baseline", "assisted")


@dataclass
class TimingResult:
    reportable: bool
    status: str
    reason: str
    target_reduction: float
    n_timers: int = 0
    n_paired_cases: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    per_timer: dict[str, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reportable": self.reportable,
            "status": self.status,
            "reason": self.reason,
            "target_reduction": self.target_reduction,
            "n_timers": self.n_timers,
            "n_paired_cases": self.n_paired_cases,
            "counts": self.counts,
            "means": {k: round(v, 4) for k, v in self.means.items()},
            "per_timer": self.per_timer,
            "warnings": self.warnings,
        }


def load_timers(path: Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        return [row for row in csv.DictReader(fh)]


def evaluate_timing(
    rows: list[dict[str, str]],
    *,
    min_timers: int = 3,
    target_reduction: float = 0.30,
) -> TimingResult:
    if not rows:
        return TimingResult(
            reportable=False,
            status="no_data",
            reason="no timing records found",
            target_reduction=target_reduction,
        )

    # (timer, case) -> {phase: minutes}
    pairs: dict[tuple[str, str], dict[str, float]] = {}
    exposure: dict[str, set[str]] = {}

    for row in rows:
        timer = (row.get("timer_id") or "").strip()
        case = (row.get("case_id") or "").strip()
        phase = (row.get("phase") or "").strip().lower()
        if not timer or not case or phase not in PHASES:
            continue
        try:
            minutes = float(row.get("minutes") or "")
        except ValueError:
            continue
        if minutes <= 0:
            continue
        pairs.setdefault((timer, case), {})[phase] = minutes
        exposure.setdefault(timer, set()).add((row.get("first_exposure") or "").strip())

    timers = sorted({timer for timer, _ in pairs})
    complete = {
        key: value for key, value in pairs.items() if all(p in value for p in PHASES)
    }

    result = TimingResult(
        reportable=False,
        status="insufficient",
        reason="",
        target_reduction=target_reduction,
        n_timers=len(timers),
    )

    if len(timers) < min_timers:
        result.reason = (
            f"{len(timers)} distinct timer(s) supplied data; {min_timers} independent timers are "
            "required. Below that threshold the metric cannot separate the tool's effect from "
            "the timer's growing familiarity with the task, so no number is reported."
        )
        result.counts = {"distinct_timers": len(timers), "paired_cases": len(complete)}
        return result

    if not complete:
        result.reason = (
            f"{len(timers)} timers present but no case has both a baseline and an assisted "
            "measurement from the same timer, so no reduction can be computed."
        )
        result.counts = {"distinct_timers": len(timers), "paired_cases": 0}
        return result

    reductions: list[float] = []
    hit = 0
    for (timer, case), value in sorted(complete.items()):
        baseline, assisted = value["baseline"], value["assisted"]
        reduction = (baseline - assisted) / baseline if baseline else 0.0
        reductions.append(reduction)
        if reduction >= target_reduction:
            hit += 1
        result.per_timer.setdefault(timer, {})[case] = round(reduction, 4)

    for timer, seen in exposure.items():
        if "assisted_first" in seen and "baseline_first" not in seen:
            result.warnings.append(
                f"timer {timer} ran the assisted condition first; their baseline may be "
                "contaminated by familiarity"
            )

    result.reportable = True
    result.status = "reported"
    result.reason = (
        f"{len(timers)} independent timers, {len(complete)} paired measurement(s); "
        "no single timer's timings are used on their own"
    )
    result.counts = {
        "distinct_timers": len(timers),
        "paired_cases": len(complete),
        "cases_meeting_target": hit,
    }
    result.means = {
        "mean_reduction": statistics.mean(reductions),
        "median_reduction": statistics.median(reductions),
        "min_reduction": min(reductions),
        "max_reduction": max(reductions),
    }
    return result
