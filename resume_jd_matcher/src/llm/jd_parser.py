"""Job-description parsing.

The JD is the untrusted input (instructor feedback: "LLM01 is fair, the JD is
untrusted text"). It is sanitised, fenced, and parsed into hard requirements.

`required_skills` is the denominator of the coverage metric, so it gets a
deterministic second pass: any canonical skill literally present in the JD text
is unioned into the model's list. Without that, a model that under-lists skills
inflates its own coverage score, which would make the metric self-serving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.llm import prompts
from src.llm.client import LLMResult, OpenRouterClient
from src.sanitize import wrap_untrusted
from src.taxonomy import match_skills, normalise_skill, ordered_skills

_MIN_SKILL_CHARS = 2
_SOFT_FILLER = {
    "team player",
    "communication",
    "communications",
    "self-starter",
    "attention to detail",
    "fast-paced",
    "fast paced",
    "proactive",
    "passionate",
    "motivated",
    "hard working",
    "detail-oriented",
    "detail oriented",
    "interpersonal skills",
    "problem solving",
    "problem-solving",
}


@dataclass
class JDParsed:
    raw_text: str
    required_skills: list[str]      # model list + deterministic literal pass
    model_skills: list[str]
    literal_skills: list[str]
    responsibilities: list[str]
    seniority: str
    years_experience: int | None
    llm: LLMResult | None = None
    notes: list[str] = field(default_factory=list)


def _tidy_skills(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if len(candidate) < _MIN_SKILL_CHARS:
            continue
        if normalise_skill(candidate) in {normalise_skill(s) for s in _SOFT_FILLER}:
            continue
        key = normalise_skill(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def parse_jd(jd_text: str, *, client: OpenRouterClient | None = None) -> JDParsed:
    client = client or OpenRouterClient()
    fenced = wrap_untrusted(jd_text, label="JOB_DESCRIPTION")

    result = client.complete_json(
        system=prompts.JD_PARSER_SYSTEM,
        user=prompts.jd_parser_user(fenced),
        task="jd_parse",
        stub_input={"jd_text": jd_text},
    )

    payload = result.content or {}
    model_skills = _tidy_skills(payload.get("required_skills"))

    # Deterministic second pass. See module docstring for the rationale.
    literal = ordered_skills(match_skills(jd_text))

    merged = {normalise_skill(s): s for s in model_skills}
    for skill in literal:
        merged.setdefault(normalise_skill(skill), skill)

    responsibilities = [
        str(r).strip() for r in (payload.get("responsibilities") or []) if str(r).strip()
    ][:6]

    years = payload.get("years_experience")
    years_int: int | None
    try:
        years_int = int(years) if years is not None else None
    except (TypeError, ValueError):
        years_int = None

    notes: list[str] = []
    if literal:
        notes.append(
            f"literal pass added {len(set(literal) - set(model_skills))} skill(s) the model omitted"
        )

    return JDParsed(
        raw_text=jd_text,
        required_skills=list(merged.values()),
        model_skills=model_skills,
        literal_skills=literal,
        responsibilities=responsibilities,
        seniority=str(payload.get("seniority") or "unspecified"),
        years_experience=years_int,
        llm=result,
        notes=notes,
    )
