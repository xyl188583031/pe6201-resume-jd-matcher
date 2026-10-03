"""Reporting.

Three outputs, all regenerable from `artifacts/runs.jsonl` plus
`data/cases/ground_truth.csv`:

    artifacts/metrics.csv       one row per condition, counts first
    artifacts/case_scores.csv   one row per case x condition, the audit trail
    artifacts/report.md         the human-readable summary

Reporting rules this module enforces, from the Milestone 1 instructor feedback:

1. COUNTS are the unit. "17/20", not "85%". A percentage may appear next to a
   count, never instead of it. "20 cases ... against a 16/20 pass bar - one miss
   is five points."
2. A run that used the offline stub is labelled a PLUMBING CHECK at the top, in
   the headline position, and condition B/C numbers are not presented as model
   behaviour. The stub is a rule set, not a model; letting its output sit in a
   results table would be the single most misleading thing this codebase could
   do.
3. Everything a reader would need to disagree with is printed: which embedding
   backend ran, whether it was downgraded, the similarity calibration in force,
   and which parts of the claim are unverified.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.evaluation.metrics import CaseScore, ConditionMetrics, PREFILL_FIELDS
from src.evaluation.timing import TimingResult

PREVIEW_ROWS = 12


@dataclass
class RunContext:
    """Everything about the run that is not a metric."""

    run_id: str
    mode: str
    model: str
    n_cases: int
    pass_bar_fraction: float
    abstention_ceiling: float
    threshold: float
    kb: dict[str, Any]
    cost: dict[str, Any]
    conditions_run: list[str]
    started_at: str = ""
    extra_notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extra_notes is None:
            self.extra_notes = []

    @property
    def is_offline(self) -> bool:
        return self.mode == "offline_stub"


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "-"
    return f"{100.0 * numerator / denominator:.0f}%"


def _count_cell(metrics: ConditionMetrics, key: str) -> str:
    return f"{metrics.counts.get(key, 0)}/{metrics.denominators.get(key, 0)}"


def write_metrics_csv(
    metrics: Sequence[ConditionMetrics],
    path: Path,
    pass_bar_fraction: float = 0.80,
    abstention_ceiling: float = 0.30,
) -> None:
    # The bar has to be passed in rather than hard-coded. This writer first
    # called as_row(0.0, 0.0), which set the minimum to 0 and made
    # `meets_pass_bar` a constant 1 - so the shipped metrics.csv asserted that
    # condition A's 13/20 met a 16/20 bar.
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [m.as_row(pass_bar_fraction, abstention_ceiling) for m in metrics]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_case_scores_csv(scores: Sequence[CaseScore], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not scores:
        path.write_text("", encoding="utf-8")
        return
    rows = [s.as_row() for s in scores]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _headline_table(metrics: Sequence[ConditionMetrics], ctx: RunContext) -> list[str]:
    minimum = int(round(ctx.pass_bar_fraction * ctx.n_cases))
    cols = ["metric", *[f"{m.condition} ({m.label})" for m in metrics]]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]

    def row(label: str, key: str, note: str = "") -> str:
        cells = [f"{m.counts.get(key, 0)}/{m.denominators.get(key, 0)}" for m in metrics]
        if note:
            pass
        return "| " + " | ".join([label, *cells]) + " |"

    lines.append(row("**cases passing the slice bar** (zero fabrication AND all prefill fields exact)", "passed"))
    lines.append(row("JD requirement coverage, complete (named + implied)", "complete_coverage"))
    lines.append(row("zero fabricated skills", "zero_fabrication"))
    lines.append(row("all four prefill fields exact", "prefill_all_match"))
    lines.append(row("  - full name", "prefill_full_name"))
    lines.append(row("  - email", "prefill_email"))
    lines.append(row("  - education institution", "prefill_education_school"))
    lines.append(row("  - top-3 skills", "prefill_top_skills"))
    lines.append(row("abstained (all cases)", "abstained"))
    lines.append(row("abstained on hard cases (the good kind)", "abstained_on_hard"))
    lines.append(row("abstained on easy cases (the bad kind)", "abstained_on_easy"))
    lines.append("")
    lines.append(
        f"Pass bar: {minimum}/{ctx.n_cases} cases "
        f"(fraction {ctx.pass_bar_fraction:.2f}). Abstention ceiling: "
        f"{_pct(int(round(ctx.abstention_ceiling * ctx.n_cases)), ctx.n_cases)} of cases "
        f"({int(round(ctx.abstention_ceiling * ctx.n_cases))}/{ctx.n_cases})."
    )
    return lines


def _fabrication_section(metrics: Sequence[ConditionMetrics]) -> list[str]:
    lines = ["", "### Fabrication evidence", ""]
    any_fab = False
    for m in metrics:
        total = m.counts.get("total_fabrications", 0)
        lines.append(f"**Condition {m.condition}** - {total} fabricated claim(s) across {m.n_cases} cases.")
        if m.examples.get("fabricated"):
            any_fab = True
            for item in m.examples["fabricated"][:PREVIEW_ROWS]:
                lines.append(f"- {item}")
            remaining = total - len(m.examples["fabricated"][:PREVIEW_ROWS])
            if remaining > 0:
                lines.append(f"- ... and {remaining} more (see case_scores.csv)")
        lines.append("")
    lines += [
        "",
        "**Read the zero-fabrication column carefully.** Two different things can produce it:",
        "",
        "- Condition A reports zero fabrications **by construction**. A literal keyword matcher "
        "can only echo skills that are already in both documents, so it is structurally incapable "
        "of inventing one. Its zero is not evidence of good behaviour, it is evidence of low "
        "capability.",
        "- Conditions B and C report zero because the pipeline strips any claimed skill with no "
        "lexical support in the resume, and caps confidence when it has to. That is earned, and it "
        "is the number worth comparing.",
        "",
        "Either way the check is narrow: it compares claimed **skills** against the candidate's "
        "declared skill set. It does not catch an invented employer, date, or quantity. Those "
        "would need a separate check and are listed as unchecked below.",
    ]
    return lines


def _abstention_section(metrics: Sequence[ConditionMetrics], ctx: RunContext) -> list[str]:
    lines = [
        "",
        "### Abstention behaviour",
        "",
        "A hard case is defined in the Problem Statement as under 50% skill overlap, and is "
        "labelled `should_abstain` in ground_truth.csv before any model runs.",
        "",
    ]
    for m in metrics:
        hard_n = m.denominators.get("abstained_on_hard", 0)
        easy_n = m.denominators.get("abstained_on_easy", 0)
        hard_hit = m.counts.get("abstained_on_hard", 0)
        easy_miss = m.counts.get("abstained_on_easy", 0)
        lines.append(
            f"- **Condition {m.condition}**: abstained on {hard_hit}/{hard_n} hard cases "
            f"and {easy_miss}/{easy_n} easy cases."
        )
        if easy_miss:
            examples = ", ".join(m.examples.get("abstained_on_easy", [])[:6])
            lines.append(f"  - false abstentions: {examples}")
        missed = m.examples.get("missed_hard", [])
        if missed:
            lines.append(f"  - hard cases answered anyway: {', '.join(missed[:6])}")
    lines += [
        "",
        "Both bounds matter. A system that abstains on everything scores 100% on hard cases and "
        "is useless; a system that never abstains scores 0% and is dangerous. The pair of counts "
        "above is the whole story, which is why neither is collapsed into a single 'accuracy'.",
    ]
    return lines


def _prefill_section(metrics: Sequence[ConditionMetrics]) -> list[str]:
    lines = ["", "### Prefill exact match, per field", ""]
    header = ["field", *[f"{m.condition}" for m in metrics]]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    labels = {
        "full_name": "full name",
        "email": "email",
        "education_school": "education institution",
        "top_skills": "top-3 skills",
    }
    for field in PREFILL_FIELDS:
        key = f"prefill_{field}"
        cells = [_count_cell(m, key) for m in metrics]
        lines.append("| " + " | ".join([labels.get(field, field), *cells]) + " |")
    lines += [
        "",
        "Matching rule: name and email are compared after case- and punctuation-folding; "
        "institution likewise; **top-3 skills is compared as a SET**, so any three skills that "
        "are both (a) in the candidate's ground-truth profile and (b) required by the job "
        "description count as correct. The rule is fixed in `expected_top_skills` "
        "(the full pool) plus `expected_top_skills_n` in ground_truth.csv.",
        "",
        "A case where the system abstained has no prefill values, so it cannot pass the slice "
        "bar. That is the literal reading of the bar in the Problem Statement, and the cost of "
        "abstention is therefore visible in the pass count rather than hidden.",
    ]
    return lines


def _timing_section(timing: TimingResult | None) -> list[str]:
    lines = ["", "### Outcome metric: time saved (gated)", ""]
    if timing is None:
        lines.append(
            "**Not reported.** Disabled in config.yaml. The Problem Statement proposed a 30% "
            "reduction measured by timing 20 cases; with a single timer running both conditions "
            "that measurement cannot separate the tool's effect from the timer's growing "
            "familiarity with the task. Enable `timing.enabled` and supply "
            "`data/timing/timers.csv` with at least "
            "`min_independent_timers` distinct timers to report it."
        )
        return lines

    if not timing.reportable:
        lines.append(f"**NOT REPORTABLE** - status `{timing.status}`.")
        lines.append("")
        lines.append(timing.reason)
        lines.append("")
        lines.append(
            "No number is produced, deliberately. A directional figure from an invalid design is "
            "still an invalid figure once it is written down."
        )
        return lines

    lines.append(f"Reportable: {timing.reason}")
    lines.append("")
    lines.append(
        f"- cases where the reduction met the {timing.target_reduction:.0%} target: "
        f"{timing.counts.get('cases_meeting_target', 0)}/{timing.counts.get('paired_cases', 0)}"
    )
    lines.append(f"- mean reduction: {timing.means.get('mean_reduction', 0.0):.1%}")
    lines.append(f"- median reduction: {timing.means.get('median_reduction', 0.0):.1%}")
    for warning in timing.warnings:
        lines.append(f"- WARNING: {warning}")
    return lines


def _context_section(ctx: RunContext) -> list[str]:
    lines = ["", "### Run context", ""]
    lines.append(f"- run id: `{ctx.run_id}`")
    lines.append(f"- started: {ctx.started_at or '(unrecorded)'}")
    lines.append(f"- conditions run: {', '.join(ctx.conditions_run)}")
    lines.append(f"- mode: `{ctx.mode}`")
    lines.append(f"- model: `{ctx.model}`")
    lines.append(f"- abstention threshold: {ctx.threshold}")
    lines.append(f"- cases: {ctx.n_cases}")
    lines.append("")
    lines.append("**Retrieval configuration** (determines what condition C actually was):")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(ctx.kb, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    lines.append("**API usage** (estimate, not an invoice):")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(ctx.cost, indent=2, ensure_ascii=False))
    lines.append("```")
    return lines


def _honesty_section(ctx: RunContext, metrics: Sequence[ConditionMetrics]) -> list[str]:
    semantic = bool((ctx.kb.get("embedder") or {}).get("semantic", False))
    lines = ["", "### What this run does and does not establish", ""]

    if ctx.is_offline:
        lines += [
            "**This is a plumbing check, not a result.**",
            "",
            "- Condition A is real. It is a rule-based TF-IDF baseline with no model in it, so an "
            "offline run measures it exactly as a live run would.",
            "- Conditions B and C were served by the deterministic offline stub, which is a "
            "literal extractive rule set, not a language model. Their numbers describe the "
            "harness, not model behaviour.",
            "- The stub ignores retrieved notes when composing its answer, so **B versus C is not "
            "interpretable from this run**. It can only show that the retrieval path is wired up.",
            "",
            "To produce results, set `OPENROUTER_API_KEY` and re-run. Nothing else changes.",
        ]
    else:
        lines += [
            "- All three conditions ran against the live model named above.",
            "- Cost figures are estimates from the price table in config.yaml, not reconciled "
            "against an invoice.",
        ]

    lines += [
        "",
        "Retrieval caveats:",
        "",
        f"- embedding backend in force: `{(ctx.kb.get('embedder') or {}).get('backend')}`"
        f" (semantic: {semantic})",
    ]
    if not semantic:
        lines += [
            "  - This backend is **lexical, not semantic**. It cannot match a synonym to a skill "
            "name, which is precisely the capability condition C is meant to add. In this "
            "configuration the B-versus-C gap is therefore narrower than the Problem Statement "
            "assumes, and any conclusion about RAG's value from this run is under-powered.",
            "  - Install `sentence-transformers` with access to the model hub and set "
            "`retrieval.embedding_backend: sentence_transformers` to get the semantic condition.",
        ]
    if (ctx.kb.get("notes") or []):
        lines.append("- store notes:")
        for note in ctx.kb["notes"]:
            lines.append(f"  - {note}")

    lines += [
        "",
        "What is NOT checked by this evaluation:",
        "",
        "- invented employers, dates, or quantities (only invented *skills* are checked)",
        "- match_score calibration (reported as a mean, never validated against expert judgement)",
        "- behaviour on real job descriptions or real resumes - the Problem Statement scopes the "
        "prototype to synthetic data and a simulated form",
    ]
    if ctx.extra_notes:
        lines.append("")
        lines.append("Run notes:")
        for note in ctx.extra_notes:
            lines.append(f"- {note}")
    return lines


def build_report(
    metrics: Sequence[ConditionMetrics],
    scores: Sequence[CaseScore],
    ctx: RunContext,
    *,
    timing: TimingResult | None = None,
) -> str:
    minimum = int(round(ctx.pass_bar_fraction * ctx.n_cases))
    lines: list[str] = [
        f"# Evaluation report - {ctx.run_id}",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`eval/run_eval.py`. Every number below is recomputable from `artifacts/runs.jsonl` "
        "and `data/cases/ground_truth.csv`.",
        "",
    ]

    if ctx.is_offline:
        lines += [
            "> ## PLUMBING CHECK - NOT RESULTS",
            "> ",
            "> This run used the offline stub for conditions B and C. The tables measure whether "
            "the pipeline, metrics and reporting work end to end. They do **not** measure model "
            "behaviour, and B-versus-C is meaningless here. Condition A is real.",
            "",
        ]

    lines += [
        "## Headline (counts)",
        "",
        f"The slice bar is **{minimum}/{ctx.n_cases}** cases, per Problem Statement section 9. "
        "Counts are the reporting unit: with 20 cases one case is 5 points, so a percentage hides "
        "the thing you actually need to see.",
        "",
        *_headline_table(metrics, ctx),
        "",
        "Mean values (context only, not the headline):",
        "",
        "| measure | " + " | ".join(m.condition for m in metrics) + " |",
        "|" + "---|" * (len(metrics) + 1),
        "| mean requirement coverage | "
        + " | ".join(f"{m.means.get('coverage', 0.0):.2f}" for m in metrics)
        + " |",
        "| mean match score | "
        + " | ".join(f"{m.means.get('match_score', 0.0):.1f}" for m in metrics)
        + " |",
        "| mean confidence | "
        + " | ".join(f"{m.means.get('confidence', 0.0):.2f}" for m in metrics)
        + " |",
        "",
        "## Detail",
        *_fabrication_section(metrics),
        *_abstention_section(metrics, ctx),
        *_prefill_section(metrics),
        *_context_section(ctx),
        *_timing_section(timing),
        *_honesty_section(ctx, metrics),
        "",
        "## Files",
        "",
        "- `artifacts/runs.jsonl` - one JSON record per condition x case, including the retrieved "
        "chunk ids, both confidence components, and the abstention reason",
        "- `artifacts/case_scores.csv` - the per-case audit trail behind every count above",
        "- `artifacts/metrics.csv` - the headline table, machine-readable",
        "",
    ]
    return "\n".join(lines)


def write_report(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
