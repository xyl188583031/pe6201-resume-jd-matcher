"""Resume -> structured prefill extraction.

Kept backward compatible on purpose: `extract_resume_fields(resume_text, api_key)`
keeps its old name, so the earlier prototype cell that imported it still runs.
New code should call `extract_prefill`, which also returns the LLM metadata
(mode, tokens, cost) the run log needs.

The hard rule from the Problem Statement (section 8, Risk 1) is enforced here as
well as in the prompt: an absent field is `None`, never a plausible guess. A
post-check drops any value that does not appear in the source text, because
prompt instructions do get ignored occasionally and a silent fabrication is the
worst possible failure for this product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src import config
from src.llm import prompts
from src.llm.client import LLMResult, OpenRouterClient

# Every field a prefill value can appear in. Listed together because the
# confidence of an *absent* field has to be zeroed: a model that returns null
# while reporting 0.9 for the same field would otherwise leave a confident
# number attached to nothing. This was originally the four evaluated fields
# only, which is why a value-bearing field outside that set could end up
# labelled `suggested` while displaying a confidence of 0.00.
_ALL_PREFILL_FIELDS = (
    "full_name",
    "email",
    "phone",
    "education_school",
    "education_degree",
    "education_major",
    "graduation_year",
    "top_skills",
)


class FabricationGuard:
    """Rejects extracted values with no support in the source text.

    Comparison is case- and punctuation-insensitive, but it must also be
    WORD-BOUNDED. An earlier revision used a plain substring test, on the theory
    that we are catching inventions rather than typos. That was wrong in the
    expensive direction: "java" is a substring of "javascript", so a model claim
    of Java survived against a resume whose only JVM-adjacent skill was
    JavaScript. The guard reported success and the fabrication was displayed.
    `src/taxonomy.has_lexical_support` was fixed for this first; the prefill path
    kept the old test and the defect stayed latent until the top_skills contract
    changed what the model put in that field.

    Matching is deliberately conservative: a value that is not found is dropped,
    which costs a suggestion and never ships a false claim.
    """

    def __init__(self, source_text: str) -> None:
        self._haystack = self._normalise(source_text)

    @staticmethod
    def _normalise(text: str) -> str:
        joined = "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace())
        # Collapse whitespace so a phrase that wraps a line break still matches.
        return re.sub(r"\s+", " ", joined).strip()

    @staticmethod
    def _contains(haystack: str, needle: str) -> bool:
        """Boundary-anchored containment: `java` must not match inside `javascript`."""
        return bool(
            re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack)
        )

    def supports(self, value: str | None) -> bool:
        if not value:
            return False
        needle = self._normalise(value)
        if not needle:
            return False
        if self._contains(self._haystack, needle):
            return True
        # Fallback for a value that was re-ordered or re-punctuated: every
        # substantial token must appear, each of them word-bounded. The token
        # test is boundary-anchored too - that is the whole point of the fix.
        tokens = [t for t in needle.split() if len(t) > 2]
        if not tokens:
            return False
        return all(self._contains(self._haystack, token) for token in tokens)


@dataclass
class PrefillResult:
    fields: dict[str, Any]
    field_confidence: dict[str, float]
    top_skills: list[str]
    dropped_ungrounded: list[str]
    llm: LLMResult


def extract_prefill(
    resume_text: str,
    *,
    jd_text: str = "",
    form_schema_block: str = "",
    client: OpenRouterClient | None = None,
) -> PrefillResult:
    """Run the prefill task and drop anything the source text cannot support."""
    client = client or OpenRouterClient()

    result = client.complete_json(
        system=prompts.PREFILL_SYSTEM,
        user=prompts.prefill_user(
            candidate_block=resume_text,
            jd_block=jd_text,
            form_schema_block=form_schema_block,
        ),
        task="prefill",
        stub_input={"candidate_text": resume_text, "jd_text": jd_text},
    )

    raw = result.content or {}
    personal = dict(raw.get("personal_info") or {})
    education = dict(raw.get("education") or {})
    top_skills = [str(s) for s in (raw.get("top_skills") or []) if s]

    guard = FabricationGuard(resume_text)
    dropped: list[str] = []

    for key in ("full_name", "email", "phone"):
        value = personal.get(key)
        if value and not guard.supports(str(value)):
            dropped.append(f"personal_info.{key}={value!r}")
            personal[key] = None

    for key in ("school", "major"):
        # Degree shorthand and years are legitimately reworded ("MSc" vs
        # "Master of Science"), so only specific claims are dropped.
        value = education.get(key)
        if value and not guard.supports(str(value)):
            dropped.append(f"education.{key}={value!r}")
            education[key] = None

    kept_skills: list[str] = []
    for skill in top_skills:
        if guard.supports(skill):
            kept_skills.append(skill)
        else:
            dropped.append(f"top_skills={skill!r}")

    fields = {
        "full_name": personal.get("full_name"),
        "email": personal.get("email"),
        "phone": personal.get("phone"),
        "education_school": education.get("school"),
        "education_degree": education.get("degree"),
        "education_major": education.get("major"),
        "graduation_year": education.get("graduation_year"),
        "top_skills": kept_skills[:3],
    }

    # A guard-dropped field must not keep its optimistic model confidence.
    field_conf = {str(k): float(v or 0.0) for k, v in (raw.get("field_confidence") or {}).items()}
    for name in _ALL_PREFILL_FIELDS:
        if not fields.get(name):
            field_conf[name] = 0.0

    return PrefillResult(
        fields=fields,
        field_confidence=field_conf,
        top_skills=kept_skills[:3],
        dropped_ungrounded=dropped,
        llm=result,
    )


def extract_resume_fields(resume_text: str, api_key: str | None = None) -> dict[str, Any]:
    """Backwards-compatible wrapper.

    Returns the nested dict shape the original prototype returned, so existing
    callers keep working. New code should prefer `extract_prefill`.
    """
    client = OpenRouterClient(api_key=api_key)
    result = client.complete_json(
        system=prompts.PREFILL_SYSTEM,
        user=prompts.prefill_user(
            candidate_block=resume_text,
            jd_block="(not supplied)",
            form_schema_block="personal_info, education, top_skills",
        ),
        task="prefill",
        stub_input={"candidate_text": resume_text, "jd_text": ""},
    )
    raw = dict(result.content or {})
    guard = FabricationGuard(resume_text)

    personal = dict(raw.get("personal_info") or {})
    if not personal.get("full_name") and personal.get("name"):
        personal["full_name"] = personal.get("name")  # older key name
    for key in ("full_name", "email", "phone"):
        if personal.get(key) and not guard.supports(str(personal[key])):
            personal[key] = None

    education = dict(raw.get("education") or {})
    for key in ("school", "major"):
        if education.get(key) and not guard.supports(str(education[key])):
            education[key] = None

    skills = [s for s in (raw.get("top_skills") or []) if guard.supports(str(s))]

    return {
        "personal_info": personal,
        "education": education,
        "work_experience": raw.get("work_experience") or [],
        "skills": skills,
    }


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    cfg = config.LLMConfig.load()
    demo = "Full Name: Zhang Wei\nEmail: zhang.wei@example.edu\nMSc in Computer Science"
    print("mode:", "offline_stub" if OpenRouterClient().offline else f"live:{cfg.model}")
    print(extract_resume_fields(demo))
