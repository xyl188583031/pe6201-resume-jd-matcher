"""Field extraction by rules.

Shared by condition A (the rule-based baseline) and by the offline stub, so the
two agree on what a regex can and cannot see. Keeping one copy also means a fix
to the email pattern does not silently apply to only half the experiment.

Everything here is literal. Nothing is inferred, and an absent field is `None`.
"""

from __future__ import annotations

import re
from typing import Any

from src.taxonomy import canonicalise, match_skills, ordered_skills

_EMAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{4}")
_NAME_LABELS = ("full name", "name", "candidate")
# [ \t]+ rather than \s+: the original used \s+, which matched across the
# newline and captured "EDUCATION\nNanyang Technological University" as the
# institution. Caught by comparing the prefill output against ground truth in
# the first end-to-end run.
_SCHOOL_RE = re.compile(
    r"([A-Z][A-Za-z&\.\-']*(?:[ \t]+[A-Z][A-Za-z&\.\-']*)*"
    r"[ \t]+(?:University|Institute of Technology|College|Polytechnic))"
)
_DEGREE_RE = re.compile(
    r"\b(Bachelor(?:'s)?(?:\s+of\s+[A-Za-z]+)?|Master(?:'s)?(?:\s+of\s+[A-Za-z]+)?|"
    r"B\.?Sc|M\.?Sc|B\.?Eng|M\.?Eng|PhD|Doctorate)\b",
    re.I,
)
_MAJOR_RE = re.compile(
    r"\b(?:in|of)\s+((?:Artificial Intelligence|Computer Science|Software Engineering|"
    r"Data Science|Data Analytics|Information Systems|Business Analytics|"
    r"Product Management|Machine Learning|Computer Engineering|Statistics))\b",
    re.I,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip(" -*\t")
        if stripped:
            return stripped
    return ""


def extract_name(text: str) -> str | None:
    for line in text.splitlines():
        low = line.lower()
        for label in _NAME_LABELS:
            idx = low.find(label + ":")
            if idx != -1:
                value = line[idx + len(label) + 1 :].strip(" \t-|")
                if value:
                    return value
    head = first_nonempty_line(text)
    # A bare first line only counts when it looks like a person's name:
    # 2-4 capitalised words, no digits.
    if head and 2 <= len(head.split()) <= 4 and not any(ch.isdigit() for ch in head):
        if all(w[:1].isupper() for w in head.split() if w[:1].isalpha()):
            return head
    return None


def extract_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    return match.group(0).strip() if match else None


def extract_school(text: str) -> str | None:
    match = _SCHOOL_RE.search(text)
    return match.group(1).strip() if match else None


def extract_degree(text: str) -> str | None:
    match = _DEGREE_RE.search(text)
    return match.group(1).strip() if match else None


def extract_major(text: str) -> str | None:
    match = _MAJOR_RE.search(text)
    return match.group(1).strip() if match else None


def extract_graduation_year(text: str) -> str | None:
    years = _YEAR_RE.findall(text)
    return max(years) if years else None


def rank_skills(candidate_text: str, jd_text: str, limit: int = 3) -> list[str]:
    """Skills the candidate demonstrably has, JD-relevant ones first."""
    cand = match_skills(candidate_text)
    jd = match_skills(jd_text)
    preferred = ordered_skills(cand & jd) or ordered_skills(cand)
    return [canonicalise(s) for s in preferred[:limit]]


def extract_fields(candidate_text: str, jd_text: str = "") -> dict[str, Any]:
    """The rule-based prefill, in the same shape the model path produces."""
    name = extract_name(candidate_text)
    email = extract_email(candidate_text)
    phone = extract_phone(candidate_text)
    school = extract_school(candidate_text)
    degree = extract_degree(candidate_text)
    major = extract_major(candidate_text)
    year = extract_graduation_year(candidate_text)
    top_skills = rank_skills(candidate_text, jd_text)

    fields = {
        "full_name": name,
        "email": email,
        "phone": phone,
        "education_school": school,
        "education_degree": degree,
        "education_major": major,
        "graduation_year": year,
        "top_skills": top_skills,
    }

    # Confidence here reports what the rules actually captured, not an opinion.
    #
    # Every field the extractor can emit gets an entry. The first four are the
    # fields the evaluation scores, and their values were fixed by the Problem
    # Statement; the remaining four are literal extractions that the form still
    # renders. They are listed because *omitting* one is not neutral: a field
    # with a value and no entry used to fall through to 0.0 and be labelled
    # `suggested` anyway, which reads as a confident suggestion carrying zero
    # confidence. The numbers below are mechanism-based, not calibrated -
    # `graduation_year` is the lowest of the four because it is the only one
    # that guesses (it takes the largest year in the document).
    field_confidence = {
        "full_name": 0.85 if name else 0.0,
        "email": 0.95 if email else 0.0,
        "education_school": 0.70 if school else 0.0,
        "top_skills": 0.60 if len(top_skills) >= 3 else (0.35 if top_skills else 0.0),
        "phone": 0.75 if phone else 0.0,
        "education_degree": 0.80 if degree else 0.0,
        "education_major": 0.80 if major else 0.0,
        "graduation_year": 0.55 if year else 0.0,
    }

    return {"fields": fields, "field_confidence": field_confidence}
