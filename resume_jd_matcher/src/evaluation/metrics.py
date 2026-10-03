"""Scoring.

Deliberately dumb, on purpose. Every check is exact match or a binary human-
verifiable predicate - no LLM-as-judge (PS section 7: "We do NOT use
LLM-as-judge ... to avoid model-judge calibration issues"). If a number here
cannot be recomputed from `runs.jsonl` plus `ground_truth.csv` by hand, it is
not a metric, it is an opinion.

Unit of report is a COUNT (instructor feedback, Milestone 1 DATA: "one miss is
five points. Report counts rather than percentages"). Every metric therefore
carries `numerator / denominator` and a rate is derived, never primary.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.taxonomy import canonicalise, normalise_skill

PREFILL_FIELDS = ("full_name", "email", "education_school", "top_skills")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(sorted(normalise_skill(str(v)) for v in value if str(v).strip()))
    return normalise_skill(str(value))


def _skill_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        parts = [p for p in value.replace(";", "|").replace(",", "|").split("|")]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = [str(value)]
    out: set[str] = set()
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        out.add(normalise_skill(canonicalise(text)))
    return out


@dataclass
class GroundTruth:
    case_id: str
    job_family: str
    variant: str
    jd_required_skills: list[str]
    candidate_skills: list[str]
    expected_prefill: dict[str, Any]
    skill_overlap: float
    hard_case: bool
    should_abstain: bool
    expected_top_skills_n: int = 3

    def __post_init__(self) -> None:
        """Normalise the skill fields, whatever the caller passed.

        `from_row` used to be the only path that normalised, so a GroundTruth
        built directly in a test compared "Python" against a normalised
        "python" and every coverage assertion failed. Normalising in one place
        removes the whole class of bug: the scoring code can now assume
        normalised sets and nothing downstream has to remember.
        """
        self.jd_required_skills = sorted(_skill_set(self.jd_required_skills))
        self.candidate_skills = sorted(_skill_set(self.candidate_skills))

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "GroundTruth":
        return cls(
            case_id=row["case_id"],
            job_family=row.get("job_family", ""),
            variant=row.get("variant", ""),
            jd_required_skills=sorted(_skill_set(row.get("jd_required_skills", ""))),
            candidate_skills=sorted(_skill_set(row.get("candidate_skills", ""))),
            expected_prefill={
                "full_name": row.get("expected_full_name", ""),
                "email": row.get("expected_email", ""),
                "education_school": row.get("expected_education_school", ""),
                "top_skills": row.get("expected_top_skills", ""),
            },
            skill_overlap=float(row.get("skill_overlap") or 0.0),
            hard_case=str(row.get("hard_case", "")).strip().lower() in {"1", "true", "yes"},
            should_abstain=str(row.get("should_abstain", "")).strip().lower() in {"1", "true", "yes"},
            expected_top_skills_n=int(row.get("expected_top_skills_n") or 3),
        )


def load_ground_truth(path: Path) -> dict[str, GroundTruth]:
    if not path.exists():
        raise FileNotFoundError(f"ground truth not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as fh:
        return {row["case_id"]: GroundTruth.from_row(row) for row in csv.DictReader(fh)}


@dataclass
class CaseScore:
    case_id: str
    condition: str
    job_family: str
    variant: str

    coverage: float = 0.0
    extracted_skills: list[str] = field(default_factory=list)
    complete_coverage: bool = False

    fabricated: list[str] = field(default_factory=list)
    zero_fabrication: bool = True

    prefill_match: dict[str, bool] = field(default_factory=dict)
    prefill_all_match: bool = False

    abstained: bool = False
    should_abstain: bool = False
    hard_case: bool = False

    match_score: int = 0
    confidence: float = 0.0
    retrieved_chunk_ids: list[str] = field(default_factory=list)

    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """PS section 9 pass condition for a single case.

        Zero fabricated skills AND the four exact-match prefill fields agree
        AND the system did not decline.

        The abstention clause is load-bearing and was missing at first. On a
        decline the runner zeroes every field confidence and replaces the
        suggestion list with a decline notice, so the prefill the user is shown
        is empty while `record["prefill"]` still holds the raw extraction. A
        scorer that ignored `abstained` therefore graded - and credited - output
        the user never received. The three components are also reported as their
        own columns, so the abstention cost stays visible in its own right.
        """
        return (
            self.zero_fabrication
            and self.prefill_all_match
            and not self.abstained
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "condition": self.condition,
            "job_family": self.job_family,
            "variant": self.variant,
            "coverage": round(self.coverage, 4),
            "complete_coverage": int(self.complete_coverage),
            "fabricated_count": len(self.fabricated),
            "fabricated_items": "; ".join(self.fabricated),
            "zero_fabrication": int(self.zero_fabrication),
            **{f"prefill_{k}": int(v) for k, v in self.prefill_match.items()},
            "prefill_all_match": int(self.prefill_all_match),
            "abstained": int(self.abstained),
            "should_abstain": int(self.should_abstain),
            "hard_case": int(self.hard_case),
            "passed": int(self.passed),
            "match_score": self.match_score,
            "confidence": round(self.confidence, 4),
            "retrieved_chunks": "; ".join(self.retrieved_chunk_ids),
            "errors": " | ".join(self.errors),
        }


def score_case(record: dict[str, Any], gt: GroundTruth) -> CaseScore:
    condition = str(record.get("condition", ""))
    score = CaseScore(
        case_id=gt.case_id,
        condition=condition,
        job_family=gt.job_family,
        variant=gt.variant,
        abstained=bool(record.get("abstained")),
        should_abstain=gt.should_abstain,
        hard_case=gt.hard_case,
        match_score=int(record.get("match_score") or 0),
        confidence=float(record.get("confidence") or 0.0),
        retrieved_chunk_ids=list(record.get("retrieved_chunk_ids") or []),
        errors=list(record.get("errors") or []),
    )

    # ---- 1. JD requirement extraction completeness -----------------------
    required = set(gt.jd_required_skills)
    extracted = _skill_set(record.get("jd_skills") or [])
    score.extracted_skills = sorted(extracted)
    score.coverage = (len(extracted & required) / len(required)) if required else 0.0
    score.complete_coverage = bool(required) and extracted >= required

    # ---- 2. fabrication ---------------------------------------------------
    # A "claim" is any skill the system attributes to the candidate. Anything
    # the candidate's ground-truth profile does not contain is a fabrication,
    # whether it appeared in the match report or in the prefill output.
    candidate = set(gt.candidate_skills)
    # Report fabricated items in their canonical spelling ("Kubernetes"), not the
    # normalised comparison form ("kubernetes"). The comparison needs
    # normalisation; the report needs to be readable.
    claimed_by_norm: dict[str, str] = {}
    for item in list(record.get("claimed_items") or []) + list(record.get("top_skills") or []):
        text = str(item).strip()
        if not text:
            continue
        canonical = canonicalise(text)
        claimed_by_norm.setdefault(normalise_skill(canonical), canonical)
    score.fabricated = sorted(
        canonical for norm, canonical in claimed_by_norm.items() if norm not in candidate
    )
    score.zero_fabrication = not score.fabricated

    # ---- 3. prefill exact match ------------------------------------------
    prefill = record.get("prefill") or {}
    for name in PREFILL_FIELDS:
        expected_raw = gt.expected_prefill.get(name)
        got_raw = prefill.get(name)
        if name == "top_skills":
            # Subset-plus-count rule, not set equality. `expected_top_skills`
            # holds the whole pool of skills that are both (a) in the
            # candidate's ground-truth profile and (b) required by the JD; the
            # system should return `expected_top_skills_n` of them, and ANY n
            # from the pool is correct. Set equality was wrong: it failed every
            # case where the pool was larger than 3, penalising a system for
            # picking a different-but-valid three.
            pool = _skill_set(expected_raw)
            got_set = _skill_set(got_raw)
            n_expected = gt.expected_top_skills_n
            ok = n_expected > 0 and len(got_set) == n_expected and got_set <= pool
        else:
            ok = bool(_norm(expected_raw)) and _norm(expected_raw) == _norm(got_raw)
        score.prefill_match[name] = ok
    score.prefill_all_match = all(score.prefill_match.values())

    return score


@dataclass
class ConditionMetrics:
    condition: str
    label: str
    n_cases: int
    counts: dict[str, int] = field(default_factory=dict)
    denominators: dict[str, int] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    examples: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def rate(self, key: str) -> float:
        denom = self.denominators.get(key, 0)
        return (self.counts.get(key, 0) / denom) if denom else 0.0

    def fmt(self, key: str) -> str:
        """The count-first display string, e.g. '17/20'."""
        return f"{self.counts.get(key, 0)}/{self.denominators.get(key, 0)}"

    def as_row(self, pass_bar_fraction: float, abstention_ceiling: float) -> dict[str, Any]:
        minimum = int(round(pass_bar_fraction * self.n_cases))
        return {
            "condition": self.condition,
            "label": self.label,
            "n_cases": self.n_cases,
            "passed_cases": self.counts.get("passed", 0),
            "passed_bar": f"{self.counts.get('passed', 0)}/{self.n_cases}",
            "meets_pass_bar": int(self.counts.get("passed", 0) >= minimum),
            "complete_coverage": self.fmt("complete_coverage"),
            "zero_fabrication": self.fmt("zero_fabrication"),
            "prefill_all_match": self.fmt("prefill_all_match"),
            "prefill_name": self.fmt("prefill_full_name"),
            "prefill_email": self.fmt("prefill_email"),
            "prefill_school": self.fmt("prefill_education_school"),
            "prefill_skills": self.fmt("prefill_top_skills"),
            "abstained": self.fmt("abstained"),
            "abstained_on_hard": self.fmt("abstained_on_hard"),
            "abstained_on_easy": self.fmt("abstained_on_easy"),
            "mean_coverage": round(self.means.get("coverage", 0.0), 3),
            "mean_match_score": round(self.means.get("match_score", 0.0), 1),
            "mean_confidence": round(self.means.get("confidence", 0.0), 3),
            "total_fabrications": self.counts.get("total_fabrications", 0),
        }


def build_condition_metrics(
    condition: str,
    label: str,
    scores: Sequence[CaseScore],
    *,
    pass_bar_fraction: float = 0.80,
) -> ConditionMetrics:
    n = len(scores)
    metrics = ConditionMetrics(condition=condition, label=label, n_cases=n)

    hard = [s for s in scores if s.hard_case]
    easy = [s for s in scores if not s.hard_case]

    metrics.counts = {
        "passed": sum(1 for s in scores if s.passed),
        "passed_excluding_abstentions": sum(1 for s in scores if s.passed and not s.abstained),
        "complete_coverage": sum(1 for s in scores if s.complete_coverage),
        "zero_fabrication": sum(1 for s in scores if s.zero_fabrication),
        "prefill_all_match": sum(1 for s in scores if s.prefill_all_match),
        "prefill_full_name": sum(1 for s in scores if s.prefill_match.get("full_name")),
        "prefill_email": sum(1 for s in scores if s.prefill_match.get("email")),
        "prefill_education_school": sum(
            1 for s in scores if s.prefill_match.get("education_school")
        ),
        "prefill_top_skills": sum(1 for s in scores if s.prefill_match.get("top_skills")),
        "abstained": sum(1 for s in scores if s.abstained),
        "abstained_on_hard": sum(1 for s in hard if s.abstained),
        "abstained_on_easy": sum(1 for s in easy if s.abstained),
        "total_fabrications": sum(len(s.fabricated) for s in scores),
    }
    metrics.denominators = {
        "passed": n,
        "passed_excluding_abstentions": n,
        "complete_coverage": n,
        "zero_fabrication": n,
        "prefill_all_match": n,
        "prefill_full_name": n,
        "prefill_email": n,
        "prefill_education_school": n,
        "prefill_top_skills": n,
        "abstained": n,
        "abstained_on_hard": len(hard),
        "abstained_on_easy": len(easy),
    }
    metrics.means = {
        "coverage": (sum(s.coverage for s in scores) / n) if n else 0.0,
        "match_score": (sum(s.match_score for s in scores) / n) if n else 0.0,
        "confidence": (sum(s.confidence for s in scores) / n) if n else 0.0,
    }

    fabricated_examples: list[str] = []
    for s in scores:
        for item in s.fabricated:
            fabricated_examples.append(f"{s.case_id}: {item}")
    metrics.examples = {
        "fabricated": fabricated_examples[:20],
        "abstained_on_easy": [s.case_id for s in easy if s.abstained][:20],
        "missed_hard": [s.case_id for s in hard if not s.abstained][:20],
        "prefill_missed": [s.case_id for s in scores if not s.prefill_all_match][:20],
    }

    minimum = int(round(pass_bar_fraction * n))
    metrics.notes.append(
        f"pass bar: {minimum}/{n} cases (fraction {pass_bar_fraction:.2f}); "
        f"this condition reached {metrics.counts['passed']}/{n}"
    )
    return metrics


def score_run(
    records: Iterable[dict[str, Any]],
    ground_truth: dict[str, GroundTruth],
) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for record in records:
        case_id = str(record.get("case_id", ""))
        gt = ground_truth.get(case_id)
        if gt is None:
            continue
        scores.append(score_case(record, gt))
    return scores
