"""The pipeline: one case in, one fully-traced result out.

    PDF/text  ->  sanitise  ->  JD parse  ->  retrieve (C only)  ->  LLM/match
              ->  confidence  ->  abstention  ->  prefill suggestions

The three conditions share everything except the middle step, so a difference
between A, B and C is attributable to that step and not to prompt drift:

    A  rule-based TF-IDF baseline, no model at all
    B  prompt-only model call, no retrieved notes
    C  model call with retrieved notes in the prompt

Every result carries its own evidence: retrieved chunk ids, both confidence
components, the abstention reason, and the raw model payload's provenance. If a
number in the report cannot be traced back to one of these fields, it should not
be in the report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.baseline.tfidf import run_baseline
from src.config import ConfidenceConfig
from src.llm import prompts
from src.llm.client import LLMResult, OpenRouterClient
from src.llm.extractor import extract_prefill
from src.llm.jd_parser import JDParsed, parse_jd
from src.logging_utils import RunRecord
from src.pipeline import confidence as conf
from src.pipeline.prefill import PrefillBundle, build_prefill, load_form_schema
from src.retrieval.store import KnowledgeBase, RetrievalResult
from src.sanitize import prepare_untrusted, wrap_untrusted
from src.taxonomy import (
    canonicalise,
    has_lexical_support,
    match_skills,
    ordered_skills,
    skill_overlap,
)

CONDITION_LABELS = {
    "A": "rule-based TF-IDF baseline",
    "B": "prompt-only LLM",
    "C": "RAG-enhanced",
}


@dataclass
class PipelineResult:
    case_id: str
    condition: str
    job_family: str = ""
    variant: str = ""
    mode: str = "offline_stub"

    resume_text: str = ""
    jd_text: str = ""

    jd: JDParsed | None = None
    retrieval: RetrievalResult | None = None

    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    match_score: int = 0
    match_analysis: str = ""
    suggestions: list[str] = field(default_factory=list)

    assessment: conf.ConfidenceAssessment | None = None
    prefill: PrefillBundle | None = None
    prefill_fields: dict[str, Any] = field(default_factory=dict)

    claimed_items: list[str] = field(default_factory=list)
    # What the fabrication guard REMOVED before the user ever saw it. Kept
    # separate from `claimed_items` on purpose: claimed_items is what the system
    # presents (and therefore what the fabrication metric scores), while this is
    # what the model proposed and the guard rejected. Reporting only the first
    # makes the guard invisible; reporting only the second punishes the system
    # for a claim it never made.
    stripped_claims: list[str] = field(default_factory=list)
    input_report: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers

    @property
    def abstained(self) -> bool:
        return bool(self.assessment and self.assessment.abstain)

    @property
    def jd_skills(self) -> list[str]:
        return list(self.jd.required_skills) if self.jd else []

    @property
    def retrieved_chunk_ids(self) -> list[str]:
        return self.retrieval.chunk_ids if self.retrieval else []

    def to_record(self, run_id: str, model: str) -> RunRecord:
        return RunRecord(
            run_id=run_id,
            condition=self.condition,
            case_id=self.case_id,
            job_family=self.job_family,
            variant=self.variant,
            mode=self.mode,
            model=model,
            retrieved_chunk_ids=self.retrieved_chunk_ids,
            retrieval_similarity=float(self.assessment.retrieval or 0.0) if self.assessment else 0.0,
            retrieval_mean_similarity=float(self.retrieval.mean_score) if self.retrieval else 0.0,
            llm_self_confidence=float(self.assessment.llm_self or 0.0) if self.assessment else 0.0,
            components_present=list(self.assessment.components_present) if self.assessment else [],
            confidence=float(self.assessment.combined) if self.assessment else 0.0,
            abstained=self.abstained,
            abstention_reason=" | ".join(self.assessment.reasons) if self.assessment else "",
            jd_skills=self.jd_skills,
            top_skills=list(self.prefill_fields.get("top_skills") or []),
            prefill={
                k: (", ".join(v) if isinstance(v, list) else (v or ""))
                for k, v in self.prefill_fields.items()
            },
            suggestions=list(self.suggestions),
            claimed_items=list(self.claimed_items),
            stripped_claims=list(self.stripped_claims),
            input_report=self.input_report,
            usage=self.usage,
            latency_ms=self.latency_ms,
            errors=list(self.errors),
            notes=list(self.notes),
        )


def _build_query(jd_text: str, jd_skills: list[str]) -> str:
    """What we search the knowledge base with.

    The JD's own wording plus its canonical skills. Both, because the JD may say
    "model deployment" while the checklist chunk is indexed under "MLOps".
    """
    skills = ", ".join(jd_skills[:12])
    return f"Job requirements: {skills}. Job description excerpt: {jd_text[:400]}"


# Public alias. The web-form server path (server/services.py) retrieves notes for
# the same purpose, and the similarity calibration in config.yaml was derived
# from JD-shaped queries like this one. Building the query a second way would put
# the two call sites on different scales while both still claiming to use the
# calibrated numbers, so they share this function instead.
build_retrieval_query = _build_query


def _collect_claimed_items(
    matched_skills: list[str], top_skills: list[str]
) -> list[str]:
    """Everything the SYSTEM attributes to the candidate.

    Deliberately the post-guard lists, not the model's raw proposal. The
    fabrication metric scores what the system presents to the user, and a claim
    the guard stripped was never presented. Scoring the raw proposal instead
    made the guard's whole effect invisible: a live run where the guard caught a
    hallucinated "Java" scored identically to one where it did not.
    """
    items = [
        str(value).strip()
        for value in list(matched_skills) + list(top_skills)
        if str(value).strip()
    ]
    return items


def run_case(
    *,
    case_id: str,
    resume_text: str,
    jd_text: str,
    condition: str,
    job_family: str = "",
    variant: str = "",
    client: OpenRouterClient | None = None,
    kb: KnowledgeBase | None = None,
    cfg: ConfidenceConfig | None = None,
    form_schema: dict[str, Any] | None = None,
) -> PipelineResult:
    started = time.perf_counter()
    cfg = cfg or ConfidenceConfig.load()
    condition = condition.upper()
    if condition not in {"A", "B", "C"}:
        raise ValueError(f"unknown condition {condition!r}; expected A, B or C")

    client = client or OpenRouterClient()
    result = PipelineResult(
        case_id=case_id,
        condition=condition,
        job_family=job_family,
        variant=variant,
        resume_text=resume_text,
        jd_text=jd_text,
        mode="offline_stub" if client.offline else "live_api",
    )

    max_chars = int(config.get("privacy", "max_input_chars", default=20000))
    sanitise = bool(config.get("privacy", "sanitize_untrusted_text", default=True))

    # ---- sanitise ---------------------------------------------------------
    # Both inputs are untrusted: the JD comes from a stranger's job ad, and the
    # resume is user data that could carry pasted text from anywhere.
    if sanitise:
        jd_clean, jd_report = prepare_untrusted(jd_text, max_chars)
        resume_clean, resume_report = prepare_untrusted(resume_text, max_chars)
    else:
        jd_clean, jd_report = jd_text, {"sanitised": False}
        resume_clean, resume_report = resume_text, {"sanitised": False}

    result.input_report = {"jd": jd_report, "resume": resume_report}
    if jd_report.get("injection_hits"):
        result.notes.append(
            f"JD contained {jd_report['injection_hits']} instruction-hijack pattern(s); redacted"
        )

    jd_block = wrap_untrusted(jd_clean, label="JOB_DESCRIPTION")
    resume_block = wrap_untrusted(resume_clean, label="CANDIDATE_PROFILE")

    # ---- condition A: no model at all ------------------------------------
    if condition == "A":
        baseline = run_baseline(resume_text=resume_clean, jd_text=jd_clean)
        result.jd = JDParsed(
            raw_text=jd_clean,
            required_skills=baseline.required_skills,
            model_skills=[],
            literal_skills=baseline.required_skills,
            responsibilities=[],
            seniority="unspecified",
            years_experience=None,
            llm=None,
            notes=["condition A parses the JD with literal keyword matching only"],
        )
        result.matched_skills = baseline.matched_skills
        result.missing_skills = baseline.missing_skills
        result.match_score = baseline.match_score
        result.match_analysis = (
            f"Rule-based baseline: TF-IDF cosine {baseline.cosine:.2f}, exact skill "
            f"overlap {baseline.skill_overlap:.2f}."
        )
        result.suggestions = baseline.suggestions
        result.prefill_fields = baseline.fields
        result.claimed_items = list(baseline.matched_skills)

        assessment = conf.assess(
            retrieval_similarity=baseline.evidence_confidence,
            llm_self_confidence=None,
            cfg=cfg,
        )
        result.assessment = assessment
        result.prefill = build_prefill(
            baseline.fields,
            baseline.field_confidence,
            cfg=cfg,
            schema=form_schema,
            overall_confidence=assessment.combined,
        )
        result.notes.extend(baseline.notes)
        result.notes.append(
            "condition A has no model component; its confidence is the lexical evidence score"
        )
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result

    # ---- JD parse and retrieval (B and C) --------------------------------
    result.jd = parse_jd(jd_clean, client=client)
    result.notes.extend(result.jd.notes)
    llm_results: list[LLMResult] = []
    if result.jd.llm:
        llm_results.append(result.jd.llm)

    usage = {
        "prompt_tokens": result.jd.llm.prompt_tokens if result.jd.llm else 0,
        "completion_tokens": result.jd.llm.completion_tokens if result.jd.llm else 0,
        "est_cost_usd": result.jd.llm.est_cost_usd if result.jd.llm else 0.0,
    }

    retrieval_similarity: float | None = None
    reference_notes: str | None = None

    if condition == "C":
        if kb is None:
            result.errors.append(
                "condition C needs a knowledge base but none was supplied; "
                "falling back to no retrieval for this case"
            )
        else:
            query = _build_query(jd_clean, result.jd.required_skills)
            # NOTE: no family filter here, deliberately. `job_family` is a
            # ground-truth label; a real system would not know which family a
            # job description belongs to. Filtering retrieval by it would leak
            # the label into the prediction and inflate condition C. Retrieval
            # is therefore over the whole knowledge base and has to earn its
            # ranking on similarity alone. The similarity calibration was
            # derived unfiltered for the same reason.
            result.retrieval = kb.retrieve(query)
            # Top-1, not the mean. The similarity calibration in config.yaml is
            # derived from the best hit per query, so the component has to be
            # the same statistic or the threshold means nothing. It is also the
            # honest reading of "retrieval similarity" for an abstention rule:
            # if the single best passage is a poor match, the grounding is weak.
            retrieval_similarity = result.retrieval.top_score
            reference_notes = result.retrieval.as_prompt_block()
            if not result.retrieval.hits:
                result.errors.append("retrieval returned no chunks")
            elif result.retrieval.top_score < cfg.threshold:
                result.notes.append(
                    f"retrieval top-1 score {result.retrieval.top_score:.2f} is below "
                    f"threshold {cfg.threshold:.2f}; the answer will likely abstain"
                )

    # ---- match ------------------------------------------------------------
    match_llm = client.complete_json(
        system=prompts.MATCH_SYSTEM,
        user=prompts.match_user(
            candidate_block=resume_block,
            jd_block=jd_block,
            reference_notes=reference_notes,
        ),
        task="match",
        stub_input={
            "candidate_text": resume_clean,
            "jd_text": jd_clean,
            "retrieved_chunk_ids": result.retrieved_chunk_ids,
        },
    )
    llm_results.append(match_llm)

    payload = match_llm.content or {}
    result.matched_skills = [str(s) for s in (payload.get("matched_skills") or []) if s]
    result.missing_skills = [str(s) for s in (payload.get("missing_skills") or []) if s]
    result.match_analysis = str(payload.get("match_analysis") or "")
    result.suggestions = [str(s) for s in (payload.get("suggestions") or []) if s]
    try:
        result.match_score = int(payload.get("match_score") or 0)
    except (TypeError, ValueError):
        result.match_score = 0

    llm_self = float(payload.get("self_confidence") or 0.0)

    # Deterministic cross-check: every skill the model attributes to the
    # candidate is checked against the candidate's own text, so a hallucinated
    # "matched" skill is visible without a human reading the output.
    #
    # The comparison must be canonical on BOTH sides. The model answers in its
    # own casing ("machine learning", "natural language processing (NLP)") while
    # `match_skills` returns canonical names ("Machine Learning", "NLP"). A raw
    # set difference therefore reported every lower-cased claim as unsupported,
    # so on every live call the guard stripped the whole matched-skill list and
    # capped confidence at the fabrication cap - which silently forced the
    # system to abstain on everything. The offline stub returns canonical names,
    # so this only ever appeared on the live path.
    literal_candidate = match_skills(resume_clean)
    literal_required = set(result.jd.required_skills)
    canonical_claims = [canonicalise(s) for s in result.matched_skills if s and s.strip()]
    unsupported = ordered_skills(
        {
            claim
            for claim in canonical_claims
            if not has_lexical_support(claim, resume_clean, present=literal_candidate)
        }
    )

    assessment = conf.assess(
        retrieval_similarity=retrieval_similarity,
        llm_self_confidence=llm_self,
        cfg=cfg,
    )
    if unsupported:
        # A claim with no lexical support in the resume is stripped and the
        # confidence is capped: this is the fabrication guard, applied to the
        # match report and not only to the prefill output.
        dropped = set(unsupported)
        result.stripped_claims = list(unsupported)
        result.notes.append(
            "stripped claimed skill(s) with no lexical support in the resume: "
            + ", ".join(unsupported)
        )
        result.matched_skills = [s for s in canonical_claims if s not in dropped]
        assessment = conf.assess(
            retrieval_similarity=retrieval_similarity,
            llm_self_confidence=min(llm_self, cfg.fabrication_cap),
            cfg=cfg,
        )
    else:
        result.matched_skills = canonical_claims
    result.assessment = assessment

    # ---- prefill ---------------------------------------------------------
    schema = form_schema if form_schema is not None else load_form_schema()
    form_block = "\n".join(
        f"- {f.get('name')}: {f.get('label', f.get('name'))}" for f in schema.get("fields", [])
    )
    try:
        prefill_result = extract_prefill(
            resume_clean,
            jd_text=jd_block,
            form_schema_block=form_block,
            client=client,
        )
        llm_results.append(prefill_result.llm)
        if prefill_result.dropped_ungrounded:
            result.notes.append(
                "prefill guard dropped ungrounded value(s): "
                + "; ".join(prefill_result.dropped_ungrounded)
            )
        result.prefill_fields = prefill_result.fields
        field_conf = prefill_result.field_confidence
    except Exception as exc:  # noqa: BLE001 - a failed prefill is a failed case
        result.errors.append(f"prefill failed: {type(exc).__name__}: {exc}")
        result.prefill_fields = {}
        field_conf = {}

    result.claimed_items = _collect_claimed_items(
        result.matched_skills,
        list(result.prefill_fields.get("top_skills") or []),
    )

    if assessment.abstain:
        # Abstaining means we do not offer suggestions at all. Offering fields
        # next to an abstention banner is exactly the mixed message the
        # Problem Statement says to avoid.
        for name in list(field_conf):
            field_conf[name] = 0.0
        result.suggestions = [
            "System declined to suggest content for this case: the evidence did not "
            "clear the confidence threshold."
        ] + [
            f"Reason: {reason}" for reason in assessment.reasons[:2]
        ]

    result.prefill = build_prefill(
        result.prefill_fields,
        field_conf,
        cfg=cfg,
        schema=schema,
        overall_confidence=assessment.combined,
    )

    usage = {
        "prompt_tokens": sum(r.prompt_tokens for r in llm_results),
        "completion_tokens": sum(r.completion_tokens for r in llm_results),
        "est_cost_usd": round(sum(r.est_cost_usd for r in llm_results), 6),
        "calls": len(llm_results),
    }
    result.usage = usage
    result.latency_ms = int((time.perf_counter() - started) * 1000)

    if unsupported:
        result.notes.append(
            f"{len(unsupported)} model-claimed skill(s) had no lexical support and were removed"
        )
    result.notes.append(
        f"literal JD requirements: {len(literal_required)}; modelled: {len(result.jd.model_skills)}"
    )
    return result
