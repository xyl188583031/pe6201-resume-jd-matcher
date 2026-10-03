"""Prefill assembly tests: human-in-the-loop and per-field abstention."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import ConfidenceConfig  # noqa: E402
from src.pipeline.prefill import build_prefill, load_form_schema  # noqa: E402
from src.llm.extractor import FabricationGuard  # noqa: E402
from src.rules.fields import extract_fields  # noqa: E402

CFG = ConfidenceConfig(
    threshold=0.4, w_retrieval=0.6, w_llm_self=0.4,
    abstain_on_either=True, hard_case_overlap=0.5,
)

SCHEMA = {
    "fields": [
        {"name": "full_name", "label": "Full name", "is_list": False},
        {"name": "email", "label": "Email address", "is_list": False},
        {"name": "education_school", "label": "University", "is_list": False},
        {"name": "top_skills", "label": "Top skills", "is_list": True},
    ]
}


class TestBuildPrefill(unittest.TestCase):
    def test_confident_fields_are_offered_not_committed(self):
        bundle = build_prefill(
            {
                "full_name": "Tan Wei Ling",
                "email": "tan.weiling@example.edu",
                "education_school": "Nanyang Technological University",
                "top_skills": "Python, SQL",
            },
            {
                "full_name": 0.9,
                "email": 0.95,
                "education_school": 0.8,
                "top_skills": 0.7,
            },
            cfg=CFG,
            schema=SCHEMA,
        )
        self.assertEqual(bundle.suggestions_offered, 4)
        self.assertEqual(bundle.suggestions_withheld, 0)
        self.assertFalse(bundle.abstention_warning)
        for field in bundle.fields:
            self.assertEqual(field.status, "suggested")
            # Nothing is auto-filled: the value is a suggestion the user must accept.
            self.assertIn("click to accept", field.reason)

    def test_low_confidence_field_is_withheld_and_explained(self):
        bundle = build_prefill(
            {"full_name": "Tan Wei Ling", "email": None, "education_school": "NTU", "top_skills": "Python"},
            {"full_name": 0.9, "email": 0.95, "education_school": 0.2, "top_skills": 0.7},
            cfg=CFG,
            schema=SCHEMA,
        )
        by_name = {f.name: f for f in bundle.fields}
        self.assertEqual(by_name["education_school"].status, "abstained")
        self.assertEqual(by_name["education_school"].value, "")
        self.assertIn("withheld rather than guessed", by_name["education_school"].reason)
        self.assertTrue(bundle.abstention_warning)
        # The confident fields are still offered - one weak field does not blank the form.
        self.assertEqual(by_name["full_name"].status, "suggested")

    def test_missing_value_is_marked_empty_not_guessed(self):
        bundle = build_prefill(
            {"full_name": "Tan Wei Ling"},
            {"full_name": 0.9, "email": 0.0, "education_school": 0.0, "top_skills": 0.0},
            cfg=CFG,
            schema=SCHEMA,
        )
        by_name = {f.name: f for f in bundle.fields}
        self.assertEqual(by_name["email"].status, "empty")
        self.assertIn("left blank on purpose", by_name["email"].reason)

    def test_serialised_payload_shape(self):
        bundle = build_prefill(
            {"full_name": "Tan Wei Ling"}, {"full_name": 0.9}, cfg=CFG, schema=SCHEMA
        )
        payload = bundle.as_dict()
        self.assertIn("fields", payload)
        self.assertIn("counts", payload)
        self.assertEqual(payload["counts"]["total"], len(SCHEMA["fields"]))

    def test_list_field_is_serialised_as_text(self):
        bundle = build_prefill(
            {"top_skills": ["Python", "SQL"]}, {"top_skills": 0.8}, cfg=CFG, schema=SCHEMA
        )
        by_name = {f.name: f for f in bundle.fields}
        self.assertEqual(by_name["top_skills"].value, "Python, SQL")
        self.assertTrue(by_name["top_skills"].is_list)


class TestFormSchemaFile(unittest.TestCase):
    def test_shipped_schema_loads_and_has_the_scored_fields(self):
        schema = load_form_schema()
        names = {f["name"] for f in schema.get("fields", [])}
        for required in ("full_name", "email", "education_school", "top_skills"):
            self.assertIn(required, names)
        # The prototype banner requirement lives in the schema file too.
        self.assertIn("not for live sites", schema["meta"]["notice"].lower())


SAMPLE_RESUME = """Full Name: Tan Wei Ling
Email: tan.weiling@example.edu
Phone: +65 9123 4500

EDUCATION
Nanyang Technological University
Master of Science in Artificial Intelligence, 2027

SKILLS
Python, PyTorch, SQL
"""


class TestStatusNeverContradictsConfidence(unittest.TestCase):
    """Regression: a field must never read `suggested` while displaying a
    confidence below the threshold.

    The original bug: `field_level_abstentions` only covers the fields the
    extractor emitted a confidence for, and `build_prefill` consulted it with a
    permissive `.get(name, False)`. A field that had a value but no confidence
    entry therefore fell through to `suggested` while showing 0.00 - the system
    breaking the rule it prints in its own sidebar.
    """

    def test_value_without_a_confidence_entry_is_withheld(self):
        schema = {
            "fields": [
                {"name": "full_name", "label": "Full name"},
                {"name": "education_degree", "label": "Degree"},  # value but no entry
                {"name": "top_skills", "label": "Top skills", "is_list": True},
            ]
        }
        bundle = build_prefill(
            {"full_name": "Tan Wei Ling", "education_degree": "Master of Science"},
            {"full_name": 0.9, "top_skills": 0.6},  # education_degree deliberately absent
            cfg=CFG,
            schema=schema,
        )
        by_name = {f.name: f for f in bundle.fields}
        self.assertEqual(by_name["education_degree"].status, "abstained")
        self.assertEqual(by_name["education_degree"].value, "")
        self.assertEqual(bundle.suggestions_offered, 1)

    def test_no_suggested_field_sits_below_the_threshold(self):
        schema = load_form_schema()
        offered_values = {
            f["name"]: ("2027" if "year" in f["name"] else "some value")
            for f in schema.get("fields", [])
        }
        bundle = build_prefill(
            offered_values,
            {"full_name": 0.9, "email": 0.95, "education_school": 0.7, "top_skills": 0.6},
            cfg=CFG,
            schema=schema,
        )
        # Four fields carry a score; the other four have values but no entry, so
        # they must be withheld rather than offered at 0.00.
        self.assertEqual(bundle.suggestions_offered, 4)
        self.assertEqual(bundle.suggestions_withheld, 4)
        for field in bundle.fields:
            if field.status == "suggested":
                self.assertGreaterEqual(
                    field.confidence,
                    CFG.threshold,
                    f"{field.name} is offered as a suggestion at confidence "
                    f"{field.confidence}, below the {CFG.threshold} threshold",
                )


class TestRuleExtractorConfidenceCoverage(unittest.TestCase):
    """The rule extractor must score every field it emits a value for.

    Omitting one is not neutral: `build_prefill` cannot invent a confidence, so
    an unscored value was being withheld after the fix above - correct, but a
    silent loss of a value the extractor had already read correctly.
    """

    def test_every_emitted_field_carries_a_confidence(self):
        extracted = extract_fields(SAMPLE_RESUME)
        for name, value in extracted["fields"].items():
            if not value:
                continue
            self.assertIn(
                name,
                extracted["field_confidence"],
                f"{name} has a value but no confidence entry",
            )
            self.assertGreater(
                extracted["field_confidence"][name],
                0.0,
                f"{name} has a value but a zero confidence",
            )

    def test_the_sample_resume_exercises_every_field(self):
        # Guard against the test above passing vacuously: if the sample stopped
        # producing values, the loop would have nothing to check.
        extracted = extract_fields(SAMPLE_RESUME)
        empty = [k for k, v in extracted["fields"].items() if not v]
        self.assertEqual(empty, [], f"sample no longer populates: {empty}")


class TestFabricationGuardWordBoundaries(unittest.TestCase):
    """The prefill guard must be word-bounded, not a plain substring test.

    The defect this exists for: `supports("Java")` returned True against a
    resume whose only matching text was "JavaScript", because the guard did
    `"java" in haystack`. The claim was then displayed as fact. It was latent
    until the top_skills contract changed what the model put in that field.
    """

    RESUME = (
        "Yeo Wen Jun\n"
        "yeo.wenjun@example.edu | +65 9124 4606 | Singapore\n\n"
        "SKILLS\n"
        "Python, JavaScript, Git, REST APIs, SQL, Excel\n"
    )

    def setUp(self):
        self.guard = FabricationGuard(self.RESUME)

    def test_a_shorter_skill_does_not_match_inside_a_longer_one(self):
        self.assertFalse(self.guard.supports("Java"))
        self.assertFalse(self.guard.supports("Script"))

    def test_the_real_skill_is_still_supported(self):
        for value in ("JavaScript", "Python", "SQL", "Excel", "REST APIs"):
            self.assertTrue(self.guard.supports(value), value)

    def test_a_multi_word_value_is_matched_as_a_phrase(self):
        self.assertTrue(self.guard.supports("Yeo Wen Jun"))

    def test_an_unrelated_skill_is_still_rejected(self):
        self.assertFalse(self.guard.supports("Kubernetes"))
        self.assertFalse(self.guard.supports("TensorFlow"))

    def test_punctuated_values_match_after_normalisation(self):
        self.assertTrue(self.guard.supports("yeo.wenjun@example.edu"))

    def test_empty_values_are_never_supported(self):
        for value in (None, "", "   "):
            self.assertFalse(self.guard.supports(value))


if __name__ == "__main__":
    unittest.main()
