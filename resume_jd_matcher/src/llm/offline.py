"""Deterministic offline stub.

Why this exists: the harness, the unit tests and a freshly-cloned repo must run
with no API key and no network. That means conditions B and C need a stand-in
responder.

What this is NOT: a model. It is a literal, extractive rule set. Consequences,
stated once here and repeated in the report and in the README:

* Condition A (TF-IDF baseline) is genuinely real in an offline run - it has no
  model in it to begin with. Its numbers are meaningful.
* Conditions B and C in an offline run are WIRING CHECKS ONLY. The stub does not
  read the retrieved notes in order to reason, so B vs C cannot be interpreted as
  evidence about RAG. `eval/run_eval.py` labels such runs `offline_stub` and
  prints a warning instead of a headline results table.

The stub never reads ground-truth labels. It sees only the same text a real
model would see, so it cannot inflate scores by peeking.
"""

from __future__ import annotations

import re
from typing import Any

from src.llm.client import LLMError
from src.rules.fields import extract_fields
from src.taxonomy import canonicalise, match_skills, ordered_skills, skill_overlap

_VAGUE_MARKERS = ("various", "etc", "some experience", "familiar with", "exposure to")


def _heuristic_match_confidence(candidate_text: str, jd_text: str, overlap: float) -> float:
    """A rule-based stand-in for a model's self-reported confidence.

    Monotone in evidence, deliberately conservative:
      more overlap            -> higher confidence
      more candidate detail   -> higher confidence
      vague wording in the JD -> lower confidence
    """
    detail = min(1.0, len(candidate_text.split()) / 180.0)
    vagueness = sum(1 for m in _VAGUE_MARKERS if m in jd_text.lower())
    penalty = min(0.3, 0.1 * vagueness)
    score = 0.25 + 0.5 * overlap + 0.25 * detail - penalty
    return round(max(0.0, min(1.0, score)), 3)


def _stub_jd_parse(payload: dict[str, Any]) -> dict[str, Any]:
    jd_text = payload.get("jd_text", "")
    skills = match_skills(jd_text)

    responsibilities: list[str] = []
    for line in jd_text.splitlines():
        stripped = line.strip(" -*\t")
        if stripped and stripped[0].isupper() and len(stripped.split()) >= 3:
            responsibilities.append(stripped[:120])
        if len(responsibilities) >= 5:
            break

    low = jd_text.lower()
    if "intern" in low:
        seniority = "intern"
    elif any(w in low for w in ("entry level", "graduate", "junior")):
        seniority = "entry"
    elif any(w in low for w in ("senior", "lead")):
        seniority = "senior"
    else:
        seniority = "unspecified"

    years = None
    years_match = re.search(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years?", low)
    if years_match:
        years = int(years_match.group(1))

    return {
        "required_skills": ordered_skills(skills),
        "responsibilities": responsibilities,
        "seniority": seniority,
        "years_experience": years,
    }


def _stub_match(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_text = payload.get("candidate_text", "")
    jd_text = payload.get("jd_text", "")
    retrieved_ids: list[str] = payload.get("retrieved_chunk_ids", [])

    cand_skills = match_skills(candidate_text)
    jd_skills = match_skills(jd_text)
    matched = ordered_skills(cand_skills & jd_skills)
    missing = ordered_skills(jd_skills - cand_skills)
    overlap = skill_overlap(cand_skills, jd_skills)

    analysis = (
        f"Literal keyword overlap is {len(matched)}/{len(jd_skills)} of the stated "
        f"requirements. Matched: {', '.join(matched) or 'none'}. "
        f"Not evidenced: {', '.join(missing) or 'none'}."
    )

    suggestions = [
        f"Lead with {skill} - it is a stated requirement and appears in your data."
        for skill in matched[:3]
    ]
    if missing:
        suggestions.append(
            "Do not claim " + ", ".join(missing[:3]) + " - your data does not evidence it."
        )
    if retrieved_ids:
        # Real provenance, not a fake reasoning step: it makes C differ from B in
        # a mechanical way. It is not evidence that RAG helps.
        suggestions.append("Style notes follow retrieved chunks: " + ", ".join(retrieved_ids))

    return {
        "match_score": int(round(100 * overlap)),
        "matched_skills": matched,
        "missing_skills": missing,
        "match_analysis": analysis,
        "suggestions": suggestions,
        "self_confidence": _heuristic_match_confidence(candidate_text, jd_text, overlap),
    }


def _stub_prefill(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_text = payload.get("candidate_text", "")
    jd_text = payload.get("jd_text", "")
    extracted = extract_fields(candidate_text, jd_text)
    fields = extracted["fields"]

    return {
        "personal_info": {
            "full_name": fields["full_name"],
            "email": fields["email"],
            "phone": fields["phone"],
        },
        "education": {
            "school": fields["education_school"],
            "degree": fields["education_degree"],
            "major": fields["education_major"],
            "graduation_year": fields["graduation_year"],
        },
        "top_skills": [canonicalise(s) for s in fields["top_skills"]],
        "work_experience": [],
        "field_confidence": extracted["field_confidence"],
    }


def _stub_jd_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the JD analysis task.

    Extractive, like every stub here: it reports what is literally in the text
    and never interprets. Wiring check only.
    """
    jd_text = payload.get("jd_text", "")
    profile_text = payload.get("profile_text") or ""

    lines = [ln.strip(" -*\t") for ln in jd_text.splitlines()]
    lines = [ln for ln in lines if ln]

    title = lines[0][:120] if lines else ""
    company = ""
    match = re.search(r"(?:company|employer|organisation|organization)\s*[:\-]\s*(.+)", jd_text, re.I)
    if match:
        company = match.group(1).strip()[:80]

    location = ""
    match = re.search(r"(?:location|based in|office)\s*[:\-]?\s*([A-Za-z][A-Za-z ,\-]{2,40})", jd_text, re.I)
    if match:
        location = match.group(1).strip()[:60]

    responsibilities = [
        ln[:120]
        for ln in lines
        if ln[:1].isupper() and len(ln.split()) >= 3
        and not any(w in ln.lower() for w in ("requirement", "qualification"))
    ][:5]

    skills = ordered_skills(match_skills(jd_text))
    bonus = [
        ln[:120]
        for ln in lines
        if re.search(r"nice to have|preferred|advantageous|a plus|bonus", ln, re.I)
    ][:4]

    missing: list[str] = []
    if profile_text:
        profile_skills = match_skills(profile_text)
        missing = [s for s in skills if s not in profile_skills]

    return {
        "job_title": title,
        "company": company,
        "location": location,
        "responsibilities": responsibilities,
        "requirements": skills,
        "keywords": skills,
        "bonus_points": bonus,
        "missing_from_user_profile": missing,
    }


def _stub_webform(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the web-form drafting task.

    Copy, not judgement: for a field whose fact key the deterministic extractor
    resolved from the authorised profile, it returns that fact; for every other
    field it returns null. It cannot draft a cover letter and it does not try -
    so an offline run exercises the wiring (scrubbing, guards, response shape)
    and produces NO evidence about answer quality. Same contract as the other
    stubs, and the server labels such runs `offline_stub`.
    """
    jd_text = payload.get("jd_text", "") or ""
    jd_skills = ordered_skills(match_skills(jd_text)) if jd_text else []
    facts: dict[str, dict[str, Any]] = {
        str(item.get("key")): item for item in (payload.get("facts") or [])
    }

    out: list[dict[str, Any]] = []
    for field in payload.get("fields") or []:
        key = field.get("fact_key")
        fact = facts.get(str(key)) if key else None
        if fact and fact.get("value"):
            value = str(fact["value"])
            confidence = float(fact.get("confidence") or 0.0)
            source = str(fact.get("source") or "none")
            relevance = (
                f"Supports the posted requirement area: {', '.join(jd_skills[:3])}."
                if jd_skills
                else ""
            )
            message = "offline stub: copied verbatim from the authorised profile"
        else:
            value = None
            confidence = 0.0
            source = "none"
            relevance = ""
            message = (
                "offline stub: no deterministic value for this field; a live model "
                "may be able to draft it from the profile"
            )
        out.append(
            {
                "field_id": field.get("field_id"),
                "suggested_value": value,
                "source": source,
                "jd_relevance": relevance,
                "confidence": confidence,
                "message": message,
            }
        )

    return {
        "overall_suggestions": [
            "offline stub: deterministic extraction only - no model reasoning took place",
        ],
        "risk_flags": [],
        "fields": out,
    }


_STUBS = {
    "jd_parse": _stub_jd_parse,
    "match": _stub_match,
    "prefill": _stub_prefill,
    "jd_analyze": _stub_jd_analyze,
    "webform": _stub_webform,
}


def run_stub(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    if task not in _STUBS:
        raise LLMError(f"no offline stub for task {task!r}")
    return _STUBS[task](payload)
