"""Condition A: the rule-based TF-IDF baseline.

This is the "no AI needed" comparator from the Problem Statement section 4:

    a TF-IDF cosine-similarity matcher between JD and resume text, with exact
    keyword overlap for required skills.

No model, no key, no network. That is why, in an offline run, condition A's
numbers are real while B and C's are not.

It also has no semantic reach, which is the whole point of keeping it: it cannot
see that "built a retrieval pipeline over a local vector index" satisfies
"experience with RAG". When it abstains, it usually abstains because the wording
differed, not because the case was hard - a failure mode worth measuring rather
than hiding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.rules.fields import extract_fields
from src.taxonomy import match_skills, ordered_skills, skill_overlap

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as _sk_cosine

    _HAVE_SKLEARN = True
except Exception:  # pragma: no cover - sklearn is a declared dependency
    _HAVE_SKLEARN = False


def tfidf_cosine(a: str, b: str) -> float:
    """Cosine similarity of the two texts in a shared TF-IDF space.

    Fitted on the pair itself. With two documents that is a stable, if coarse,
    lexical overlap measure. Returns 0.0 for empty input rather than raising,
    so a blank JD becomes a failed case instead of a crash.
    """
    if not a.strip() or not b.strip():
        return 0.0
    if not _HAVE_SKLEARN:
        # Degenerate fallback: Jaccard over tokens. Reported, never silent.
        ta, tb = {w.lower() for w in a.split()}, {w.lower() for w in b.split()}
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)
    matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit_transform([a, b])
    return float(_sk_cosine(matrix[0], matrix[1])[0, 0])


@dataclass
class BaselineOutput:
    required_skills: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    match_score: int
    cosine: float
    skill_overlap: float
    suggestions: list[str]
    fields: dict[str, Any]
    field_confidence: dict[str, float]
    notes: list[str] = field(default_factory=list)

    @property
    def evidence_confidence(self) -> float:
        """The lexical evidence score, used as this condition's confidence."""
        return float(self.skill_overlap)


def run_baseline(
    *,
    resume_text: str,
    jd_text: str,
    score_weights: tuple[float, float] = (0.5, 0.5),
) -> BaselineOutput:
    w_cosine, w_overlap = score_weights
    notes: list[str] = []
    if not _HAVE_SKLEARN:
        notes.append("scikit-learn unavailable; TF-IDF replaced by token Jaccard")

    jd_skills = match_skills(jd_text)
    cand_skills = match_skills(resume_text)

    matched = ordered_skills(cand_skills & jd_skills)
    missing = ordered_skills(jd_skills - cand_skills)
    overlap = skill_overlap(cand_skills, jd_skills)
    cosine = tfidf_cosine(resume_text, jd_text)

    score = int(round(100 * (w_cosine * cosine + w_overlap * overlap)))

    suggestions: list[str] = []
    if matched:
        suggestions.append(
            "Put these required skills in your summary line: " + ", ".join(matched[:5])
        )
    if missing:
        suggestions.append(
            "These requirements have no literal match in your resume: "
            + ", ".join(missing[:5])
            + ". Reword only if your experience genuinely covers them."
        )
    if not matched and not missing:
        suggestions.append("No canonical requirements detected in the job description.")
    suggestions.append(
        "Note: this baseline matches literal keywords and cannot recognise "
        "synonyms or equivalent experience."
    )

    extracted = extract_fields(resume_text, jd_text)

    return BaselineOutput(
        required_skills=ordered_skills(jd_skills),
        matched_skills=matched,
        missing_skills=missing,
        match_score=score,
        cosine=round(cosine, 4),
        skill_overlap=round(overlap, 4),
        suggestions=suggestions,
        fields=extracted["fields"],
        field_confidence=extracted["field_confidence"],
        notes=notes,
    )
