"""Confidence scoring and the abstention rule.

The Problem Statement commits to one deterministic rule (sections 4, 6, 8):
confidence below 0.4 means the system declines instead of answering.

    confidence = w_retrieval * retrieval_similarity + w_llm * llm_self_confidence

and, per PS section 8 Risk 2, abstention also fires when *either* component
falls below the threshold. The second condition is the interesting one: it
catches the silent-failure case where retrieval was poor but the model was
confidently wrong about it.

One asymmetry has to be handled honestly. The three conditions do not all have
both components:

    A (rule-based)  : lexical evidence only, no model
    B (prompt-only) : model self-confidence only, no retrieval
    C (RAG)         : retrieval similarity AND model self-confidence

Substituting 0.0 for a missing component would be an implementation artefact
dressed up as a result - condition B would abstain on nearly every case purely
because its absent retrieval was scored as zero. So the combined score is the
weighted mean over the components that *exist*, renormalised, and the
either-component rule only applies to components that exist.
`components_present` is carried on every assessment and reported, so a reader
can always see which formula produced a given number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config import ConfidenceConfig


@dataclass
class ConfidenceAssessment:
    combined: float
    retrieval: float | None
    llm_self: float | None
    threshold: float
    abstain: bool
    reasons: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    components_present: list[str] = field(default_factory=list)
    weights_used: dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "combined": round(self.combined, 4),
            "retrieval": None if self.retrieval is None else round(self.retrieval, 4),
            "llm_self": None if self.llm_self is None else round(self.llm_self, 4),
            "threshold": self.threshold,
            "abstain": self.abstain,
            "reasons": list(self.reasons),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "components_present": list(self.components_present),
            "weights_used": {k: round(v, 4) for k, v in self.weights_used.items()},
        }


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def assess(
    *,
    retrieval_similarity: float | None,
    llm_self_confidence: float | None,
    cfg: ConfidenceConfig | None = None,
) -> ConfidenceAssessment:
    """Combine whichever components are available; abstain on weak evidence."""
    cfg = cfg or ConfidenceConfig.load()
    threshold = cfg.threshold

    retrieval = None if retrieval_similarity is None else _clip(retrieval_similarity)
    llm_self = None if llm_self_confidence is None else _clip(llm_self_confidence)

    reasons: list[str] = []
    components: dict[str, float] = {}
    weights: dict[str, float] = {}

    if retrieval is not None:
        components["retrieval"] = retrieval
        weights["retrieval"] = cfg.w_retrieval
    if llm_self is not None:
        components["llm_self"] = llm_self
        weights["llm_self"] = cfg.w_llm_self

    if not components:
        # Nothing to go on at all. Declining is the only safe answer.
        return ConfidenceAssessment(
            combined=0.0,
            retrieval=None,
            llm_self=None,
            threshold=threshold,
            abstain=True,
            reasons=["no confidence component was available; declining"],
            components={},
            components_present=[],
            weights_used={},
        )

    total_weight = sum(weights.values())
    combined = (
        sum(components[name] * weights[name] for name in components) / total_weight
        if total_weight
        else 0.0
    )

    if len(components) == 1:
        only = next(iter(components))
        reasons.append(
            f"only the {only} component exists for this condition; "
            "confidence equals that component"
        )

    abstain = combined < threshold
    if abstain:
        reasons.append(f"combined confidence {combined:.2f} < threshold {threshold:.2f}")

    if cfg.abstain_on_either:
        if "retrieval" in components and components["retrieval"] < threshold:
            abstain = True
            reasons.append(
                f"retrieval similarity {components['retrieval']:.2f} < threshold "
                f"{threshold:.2f} (retrieval looked weak, so the answer is not trusted)"
            )
        if "llm_self" in components and components["llm_self"] < threshold:
            abstain = True
            reasons.append(
                f"model self-confidence {components['llm_self']:.2f} < threshold "
                f"{threshold:.2f} (model reported it could not ground the answer)"
            )

    return ConfidenceAssessment(
        combined=combined,
        retrieval=retrieval,
        llm_self=llm_self,
        threshold=threshold,
        abstain=abstain,
        reasons=reasons,
        components=components,
        components_present=sorted(components),
        weights_used=weights,
    )


def field_level_abstentions(
    field_confidence: dict[str, float],
    *,
    cfg: ConfidenceConfig | None = None,
) -> dict[str, bool]:
    """Which prefill fields to withhold.

    A field is withheld when its own confidence is below the threshold. One
    weak field must not poison the whole form: the user still gets the fields
    we are sure about, with the uncertain ones left visibly blank.
    """
    cfg = cfg or ConfidenceConfig.load()
    return {
        name: float(confidence or 0.0) < cfg.threshold
        for name, confidence in field_confidence.items()
    }


def is_hard_case(skill_overlap_value: float, cfg: ConfidenceConfig | None = None) -> bool:
    """PS section 7: a hard case is defined as under 50% skill overlap."""
    cfg = cfg or ConfidenceConfig.load()
    return skill_overlap_value < cfg.hard_case_overlap
