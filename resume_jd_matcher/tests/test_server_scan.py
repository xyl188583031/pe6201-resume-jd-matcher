"""Tests for `POST /scan` and the field classifier behind it.

What this file is protecting: the decision about *which controls the assistant
may touch* and *which are identity documents*. Both are easy to get subtly wrong
in a way that only shows up as a wrong value written into a real form, so each
rule has a test that names the failure it prevents.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.field_map import (  # noqa: E402
    classify,
    compute_field_id,
    detect_sensitive,
    normalise_fields,
)
from server.schemas import RawField, ScanRequest  # noqa: E402
from server.services import scan  # noqa: E402
from tests.server_fixtures import field  # noqa: E402

TOKEN = "unit-test-token"
HEADERS = {"X-RJD-Token": TOKEN}


def client() -> TestClient:
    return TestClient(create_app(require_token=True, token=TOKEN))


class TestSkippedControls(unittest.TestCase):
    """Controls the assistant must never write into."""

    def test_hidden_submit_button_reset_image_file_password_are_not_fillable(self) -> None:
        raw = [
            field("csrf", tag="input", type="hidden", name="csrf"),
            field("Submit", tag="input", type="submit"),
            field("Click", tag="input", type="button"),
            field("Reset", tag="input", type="reset"),
            field("Go", tag="input", type="image"),
            field("Upload CV", tag="input", type="file"),
            field("Password", tag="input", type="password"),
            field("Full name", tag="input", type="text", name="full_name"),
        ]
        fields = normalise_fields(raw)
        fillable = [f for f in fields if f.fillable]
        self.assertEqual(len(fillable), 1)
        self.assertEqual(fillable[0].fact_key, "full_name")
        for skipped in fields[:-1]:
            self.assertFalse(skipped.fillable)
            self.assertTrue(skipped.skip_reason, "a skipped control must say why")

    def test_submit_control_is_skipped_even_when_its_label_looks_like_a_field(self) -> None:
        # "Submit application" contains "application"; the type check has to win.
        fields = normalise_fields([field("Submit application", tag="input", type="submit")])
        self.assertFalse(fields[0].fillable)

    def test_unsupported_element_is_skipped(self) -> None:
        fields = normalise_fields([field("Signature", tag="canvas")])
        self.assertFalse(fields[0].fillable)
        self.assertIn("unsupported", fields[0].skip_reason)

    def test_textarea_and_contenteditable_and_select_are_fillable(self) -> None:
        fields = normalise_fields(
            [
                field("Cover letter", tag="textarea", type="textarea"),
                field("Additional information", tag="contenteditable", type="text"),
                field("Degree", tag="select", type="select", options=["BSc", "MSc"]),
            ]
        )
        self.assertTrue(all(f.fillable for f in fields))

    def test_a_control_we_never_write_to_is_never_reported_as_pre_filled(self) -> None:
        """Regression: a button's caption and a CSRF token were read as user input.

        `already_filled` was computed from the raw `value` attribute, and for an
        `<input type="submit" value="Submit application">` that attribute is the
        button's *caption*, while a hidden input's is a CSRF token. A page where
        the user had typed nothing therefore reported four already-answered
        fields, and the panel said so.
        """
        fields = normalise_fields(
            [
                field("Submit application", tag="input", type="submit", name="submit_application"),
                field("Reset form", tag="input", type="reset", name="reset_form"),
                field("csrf", tag="input", type="hidden", name="csrf_token"),
                field("Portal password", tag="input", type="password", name="pw"),
                field("Full name", tag="input", type="text", name="full_name"),
            ]
        )
        self.assertTrue(all(not f.already_filled for f in fields))
        # The raw DOM values were genuinely present - they are just not answers.
        self.assertEqual(fields[0].current_value, "")
        self.assertEqual(fields[2].current_value, "")

    def test_a_prefilled_text_input_is_still_reported_as_pre_filled(self) -> None:
        # The other half of the same rule: a value the *user* would have typed
        # must still stop the assistant overwriting it.
        fields = normalise_fields(
            [field("Full name", tag="input", type="text", name="full_name", current_value="Zhang Wei")]
        )
        self.assertTrue(fields[0].already_filled)
        self.assertEqual(fields[0].current_value, "Zhang Wei")


class TestSensitiveDetection(unittest.TestCase):
    """Extremely sensitive fields: never generated, never filled."""

    def test_document_number_fields_are_sensitive(self) -> None:
        for label in [
            "Passport Number",
            "passport_no",
            "National ID",
            "id_number",
            "Identity Card Number",
            "NRIC",
            "MyKad No",
            "Aadhaar number",
            "Social Security Number",
            "SSN",
            "Residence Permit Number",
            "Tax Identification Number",
            "Driving Licence Number",
            "身份证号",
            "护照号",
        ]:
            with self.subTest(label=label):
                is_sensitive, reason = detect_sensitive(field(label))
                self.assertTrue(is_sensitive, f"{label!r} should be treated as sensitive")
                self.assertIn("never", reason)

    def test_separators_do_not_defeat_detection(self) -> None:
        # `\b` does not fire around `_`, so `passport_number` would slip past a
        # naive boundary test. The classifier flattens separators first.
        for label in ["passport_number", "passport-number", "passport.number", "PassportNo"]:
            with self.subTest(label=label):
                self.assertTrue(detect_sensitive(field(label))[0])

    def test_camel_case_attribute_names_are_detected(self) -> None:
        """Regression: camelCase DOM attributes used to defeat every pattern.

        `normalise_text` did not split camelCase, so `id="passportNo"` normalised
        to `passportno`, `\\bpassport\\b` did not match, and the field was reported
        as an ordinary fillable field. These are exactly the spellings a real form
        uses for its `name`/`id` attributes, so the gap was reachable in practice.
        """
        for label in [
            "PassportNo",
            "passportNumber",
            "NRICNumber",
            "idNumber",
            "id_number",
            "IdentityCardNo",
            "SocialSecurityNumber",
            "drivingLicenceNumber",
            "PassportNumber",
        ]:
            with self.subTest(label=label):
                self.assertTrue(
                    detect_sensitive(field(label))[0],
                    f"{label!r} should be treated as sensitive",
                )

    def test_camel_case_safe_ids_stay_fillable(self) -> None:
        # The other half of the same fix: the safe-id check must still win, or the
        # camelCase split would turn every "StudentID"/"EmployeeID" into a refusal.
        for label in ["StudentID", "studentId", "EmployeeID", "ApplicationID", "OrderNo"]:
            with self.subTest(label=label):
                self.assertFalse(
                    detect_sensitive(field(label))[0], f"{label!r} should stay fillable"
                )

    def test_camel_case_labels_are_classified(self) -> None:
        # Splitting camelCase also fixes classification, which previously left
        # `fullName` / `jobTitle` unmapped because `\\bfull ?name\\b` saw "fullname".
        cases = {
            "fullName": "full_name",
            "jobTitle": "internship_title",
            "projectName": "project_name",
            "graduationYear": "graduation_year",
            "CurrentCity": "location",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(classify(field(label))[2], expected)

    def test_institution_issued_ids_are_not_sensitive(self) -> None:
        # Blocking these would suppress answers users routinely need.
        for label in ["Student ID", "Student Number", "Matriculation Number", "Application ID", "Candidate Reference"]:
            with self.subTest(label=label):
                self.assertFalse(detect_sensitive(field(label))[0], f"{label!r} should be fillable")

    def test_password_like_id_alone_is_not_reported_as_sensitive(self) -> None:
        # A bare "id" is too ambiguous to call a document number; the control type
        # is what protects a password box.
        self.assertFalse(detect_sensitive(field("Reference", name="ref"))[0])


class TestClassification(unittest.TestCase):
    """Which profile fact a web form field maps onto."""

    def test_known_fields_map_to_expected_facts(self) -> None:
        cases = {
            "Full name": "full_name",
            "Email address": "email",
            "Phone": "phone",
            "University / institution": "education_school",
            "Degree": "education_degree",
            "Major": "education_major",
            "Graduation year": "graduation_year",
            "Top skills": "top_skills",
            "Company name": "internship_employer",
            "Job title": "internship_title",
            "Project description": "project_summary",
            "LinkedIn profile": "linkedin",
            "Current city": "location",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(classify(field(label))[2], expected)

    def test_narrative_fields_have_no_single_fact(self) -> None:
        for label in ["Cover letter", "Why do you want this role?", "Tell us about yourself"]:
            with self.subTest(label=label):
                category, module, fact = classify(field(label))
                self.assertEqual(category, "narrative")
                self.assertIsNone(fact)
                self.assertIsNone(module)

    def test_company_name_does_not_become_the_candidate_name(self) -> None:
        # Ordering matters: the specific pattern has to win over the `\bname\b`
        # fallback, or an employer would be entered as the applicant.
        self.assertEqual(classify(field("Company name"))[2], "internship_employer")

    def test_unknown_field_stays_unknown_and_unmapped(self) -> None:
        category, module, fact = classify(field("Favourite colour"))
        self.assertEqual(category, "unknown")
        self.assertIsNone(fact)
        self.assertIsNone(module)

    def test_module_attribution(self) -> None:
        self.assertEqual(classify(field("Email address"))[1], "personal_info")
        self.assertEqual(classify(field("Degree"))[1], "education")
        self.assertEqual(classify(field("Company name"))[1], "internship")
        self.assertEqual(classify(field("Project description"))[1], "projects")


class TestFieldIds(unittest.TestCase):
    """Stable ids, because the user's edits are stored against them."""

    def test_id_is_stable_for_the_same_control(self) -> None:
        first = normalise_fields([field("Email", name="email", id="email")])[0].field_id
        second = normalise_fields([field("Email", name="email", id="email")])[0].field_id
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("wf_"))

    def test_id_differs_for_different_controls(self) -> None:
        a = normalise_fields([field("Email", name="email")])[0].field_id
        b = normalise_fields([field("Phone", name="phone")])[0].field_id
        self.assertNotEqual(a, b)

    def test_duplicate_controls_get_distinct_ids(self) -> None:
        # A billing and a shipping email share name and label; they still need
        # separate ids or the user's per-field edit would collide.
        fields = normalise_fields(
            [
                field("Email", name="email", id="email"),
                field("Email", name="email", id="email"),
            ]
        )
        self.assertNotEqual(fields[0].field_id, fields[1].field_id)

    def test_explicit_id_is_preserved(self) -> None:
        fields = normalise_fields([field("Email", field_id="wf_supplied")])
        self.assertEqual(fields[0].field_id, "wf_supplied")

    def test_anonymous_control_still_gets_an_id(self) -> None:
        fields = normalise_fields([RawField()])
        self.assertTrue(fields[0].field_id.startswith("wf_"))


class TestScanCountsAndEndpoint(unittest.TestCase):
    def test_counts_add_up(self) -> None:
        raw = [
            field("Full name", name="full_name", required=True, max_length=60),
            field("Email", name="email", type="email", required=True),
            field("Passport Number", name="passport_no", required=True),
            field("Notes", tag="textarea", type="textarea", current_value="already typed"),
            field("csrf", tag="input", type="hidden"),
        ]
        result = scan(ScanRequest(url="https://example.test/apply", page_title="Apply", fields=raw))
        counts = result.counts
        self.assertEqual(counts.total, 5)
        self.assertEqual(counts.fillable, 4)
        self.assertEqual(counts.skipped, 1)
        self.assertEqual(counts.sensitive, 1)
        self.assertEqual(counts.required, 3)
        self.assertEqual(counts.already_filled, 1)
        self.assertTrue(any("identity documents" in note for note in result.notes))

    def test_required_and_maxlength_are_forwarded(self) -> None:
        fields = normalise_fields([field("Full name", required=True, max_length=60, selector="#fn")])
        self.assertTrue(fields[0].required)
        self.assertEqual(fields[0].max_length, 60)
        self.assertEqual(fields[0].selector, "#fn")

    def test_endpoint_requires_the_token(self) -> None:
        c = client()
        response = c.post("/scan", json={"url": "", "page_title": "", "fields": []})
        self.assertEqual(response.status_code, 401)

    def test_endpoint_returns_normalised_fields(self) -> None:
        c = client()
        body = {
            "url": "https://example.test/apply",
            "page_title": "Apply",
            "fields": [
                {
                    "tag": "input",
                    "type": "text",
                    "name": "full_name",
                    "id": "full_name",
                    "label": "Full name",
                    "placeholder": "",
                    "aria_label": "",
                    "required": True,
                    "max_length": 60,
                    "options": [],
                    "help_text": "",
                    "current_value": "",
                    "selector": "#full_name",
                },
                {
                    "tag": "input",
                    "type": "text",
                    "name": "passport_no",
                    "id": "passport_no",
                    "label": "Passport Number",
                    "placeholder": "",
                    "aria_label": "",
                    "required": True,
                    "max_length": None,
                    "options": [],
                    "help_text": "",
                    "current_value": "",
                    "selector": "#passport_no",
                },
            ],
        }
        response = c.post("/scan", json=body, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["counts"]["total"], 2)
        self.assertEqual(payload["counts"]["sensitive"], 1)
        self.assertEqual(payload["fields"][0]["fact_key"], "full_name")
        self.assertTrue(payload["fields"][1]["sensitive"])

    def test_endpoint_rejects_a_malformed_body(self) -> None:
        c = client()
        response = c.post("/scan", json={"fields": "not-a-list"}, headers=HEADERS)
        self.assertEqual(response.status_code, 422)

    def test_compute_field_id_falls_back_for_an_anonymous_control(self) -> None:
        self.assertTrue(compute_field_id(RawField(), index=7).endswith("007"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
