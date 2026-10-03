"""Pre-fill assembly for the simulated recruitment form.

Two rules from the Problem Statement, both enforced here rather than trusted to
the UI:

* Nothing is written into a field automatically. Every value is emitted as an
  editable *suggestion* that carries its own confidence; the user has to click
  to accept it (PS section 8, Risk 1: human in the loop).
* A field whose confidence is under the threshold is withheld and marked
  `abstained`, with the reason attached. One uncertain field does not blank the
  whole form - the confident ones are still offered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.config import ConfidenceConfig
from src.pipeline.confidence import field_level_abstentions

# pipeline field name -> how it should be presented
FIELD_LABELS: dict[str, str] = {
    "full_name": "Full name",
    "email": "Email address",
    "phone": "Contact number",
    "education_school": "University / institution",
    "education_degree": "Degree",
    "education_major": "Major / programme",
    "graduation_year": "Graduation year",
    "top_skills": "Top skills (comma separated)",
}


@dataclass
class PrefillField:
    name: str
    label: str
    value: str
    confidence: float
    status: str          # suggested | abstained | empty
    is_list: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "value": self.value,
            "confidence": round(float(self.confidence), 3),
            "status": self.status,
            "is_list": self.is_list,
            "reason": self.reason,
        }


@dataclass
class PrefillBundle:
    fields: list[PrefillField]
    abstention_warning: bool
    suggestions_offered: int
    suggestions_withheld: int
    overall_confidence: float
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": [f.as_dict() for f in self.fields],
            "abstention_warning": self.abstention_warning,
            "counts": {
                "offered": self.suggestions_offered,
                "withheld": self.suggestions_withheld,
                "total": len(self.fields),
            },
            "overall_confidence": round(self.overall_confidence, 3),
            "notes": list(self.notes),
        }


def load_form_schema(path: Any | None = None) -> dict[str, Any]:
    path = path or config.path("form_schema")
    if not path.exists():
        return {"form": "simulated_recruitment_form", "fields": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def build_prefill(
    system_fields: dict[str, Any],
    field_confidence: dict[str, float],
    *,
    cfg: ConfidenceConfig | None = None,
    schema: dict[str, Any] | None = None,
    overall_confidence: float | None = None,
) -> PrefillBundle:
    cfg = cfg or ConfidenceConfig.load()
    schema = schema if schema is not None else load_form_schema()

    order = [f["name"] for f in schema.get("fields", []) if "name" in f] or list(FIELD_LABELS)
    schema_by_name = {f["name"]: f for f in schema.get("fields", []) if "name" in f}

    # Cover every field this bundle will render, not just the ones the extractor
    # happened to score. A field that has a value but no confidence entry falls
    # back to 0.0 below, so it has to be withheld; leaving it out of this dict
    # let `.get(name, False)` report it as `suggested` while displaying a
    # confidence of 0.00 - the system contradicting its own threshold rule.
    withheld = field_level_abstentions(
        {name: float(field_confidence.get(name, 0.0) or 0.0) for name in order},
        cfg=cfg,
    )

    fields: list[PrefillField] = []
    offered = 0
    held = 0

    for name in order:
        meta = schema_by_name.get(name, {})
        label = str(meta.get("label") or FIELD_LABELS.get(name, name))
        is_list = bool(meta.get("is_list", name == "top_skills"))
        value = _stringify(system_fields.get(name))
        confidence = float(field_confidence.get(name, 0.0) or 0.0)

        if not value:
            fields.append(
                PrefillField(
                    name=name,
                    label=label,
                    value="",
                    confidence=0.0,
                    status="empty",
                    is_list=is_list,
                    reason="not present in the source data - left blank on purpose",
                )
            )
            continue

        # Fail-safe default: an unknown field is withheld, never offered.
        if withheld.get(name, True):
            held += 1
            fields.append(
                PrefillField(
                    name=name,
                    label=label,
                    value="",
                    confidence=confidence,
                    status="abstained",
                    is_list=is_list,
                    reason=(
                        f"field confidence {confidence:.2f} < {cfg.threshold:.2f}; "
                        "withheld rather than guessed"
                    ),
                )
            )
            continue

        offered += 1
        fields.append(
            PrefillField(
                name=name,
                label=label,
                value=value,
                confidence=confidence,
                status="suggested",
                is_list=is_list,
                reason="suggested - click to accept and edit",
            )
        )

    notes: list[str] = []
    if held:
        notes.append(
            f"{held} field(s) withheld below the {cfg.threshold:.2f} confidence threshold"
        )
    if offered:
        notes.append(f"{offered} field(s) offered as editable suggestions")

    overall = (
        float(overall_confidence)
        if overall_confidence is not None
        else (sum(f.confidence for f in fields if f.status == "suggested") / offered if offered else 0.0)
    )

    return PrefillBundle(
        fields=fields,
        abstention_warning=held > 0,
        suggestions_offered=offered,
        suggestions_withheld=held,
        overall_confidence=overall,
        notes=notes,
    )
