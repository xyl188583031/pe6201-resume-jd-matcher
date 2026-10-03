"""The two hard rules, tested as guarantees rather than as features.

    Section 5.1  extremely sensitive fields are never collected, generated or
                 transmitted - not "usually not", and not "not by default".
    Section 5.2  missing information is reported, never fabricated.

Both are stated as absolutes in the task, so the tests are written as absence
assertions: not "the response says X" but "the value appears nowhere in this
object, in any form". A guarantee that holds for the response body but not for
the prompt, or for the prompt but not for the persisted draft, is not the
guarantee the task asks for. So each rule is checked at every boundary it could
leak through:

    the scan response          -> TestScanNeverCollects
    the model prompt           -> TestNothingSensitiveReachesTheModel
    the generate response       -> TestGenerateNeverOffers
    the request body the client sends -> TestTheClientCannotSmuggle
    the missing-information path      -> TestNothingIsFabricated

The last one is the harder rule to test, because "did not fabricate" has no
positive signal - a wrong answer looks exactly like a right one. The approach
here is to make the profile's facts known exactly and then assert the response
either offers one of those exact strings or offers nothing.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.field_map import extract_facts, normalise_fields, render_profile  # noqa: E402
from server.schemas import GenerateRequest, ScanRequest  # noqa: E402
from server.services import MSG_SENSITIVE, generate, scan  # noqa: E402
from tests.server_fixtures import (  # noqa: E402
    ALL_MODULES,
    JD_TEXT,
    PROFILE,
    StubClient,
    StubKbProvider,
    field,
    webform_payload,
)

TOKEN = "unit-test-token"
HEADERS = {"X-RJD-Token": TOKEN}

#: The document numbers in play. They must not appear anywhere in any output.
PASSPORT = "E12345678"
NRIC = "S9876543Z"
LICENCE = "S1234567A"

#: Every spelling of "a government document number" the classifier must catch.
SENSITIVE_LABELS = [
    "Passport Number",
    "Passport No",
    "passport_number",
    "passportNo",
    "PassportNumber",
    "National ID",
    "National Identification Number",
    "Identity Card Number",
    "id_number",
    "idNumber",
    "NRIC",
    "NRICNumber",
    "NRIC No",
    "MyKad No",
    "Aadhaar Number",
    "Social Security Number",
    "SSN",
    "Residence Permit Number",
    "Tax Identification Number",
    "Driving Licence Number",
    "drivingLicenceNumber",
    "身份证号",
    "护照号",
]

#: Spelled-out facts from the fixture profile, used to check that an offered
#: value is one of these and not something the model invented.
PROFILE_FACTS = [
    "Zhang Wei",
    "zhang.wei@example.edu",
    "+65 9123 4567",
    "Singapore",
    "github.com/zhangwei",
    "Nanyang Technological University",
    "Master of Science",
    "Computer Science",
    "4.5",
    "Acme Corp",
    "Data Analyst Intern",
    "May 2025 - Aug 2025",
    "Built dashboards with Python and SQL for the risk team.",
    "Resume Matcher",
    "A retrieval-augmented prototype written in Python.",
]


def sensitive_page() -> list:
    return [
        field("Full name", name="full_name"),
        field("Passport Number", name="passport_no", required=True, current_value=PASSPORT),
        field("NRIC", name="nric", current_value=NRIC),
        field("Driving Licence Number", name="licence", current_value=LICENCE),
    ]


class TestScanNeverCollects(unittest.TestCase):
    """Section 5.1 at the scanning boundary."""

    def test_document_numbers_are_not_echoed_in_the_scan_response(self) -> None:
        result = scan(
            ScanRequest(url="https://example.test/apply", page_title="Apply", fields=sensitive_page())
        )
        body = result.model_dump_json()
        for number in (PASSPORT, NRIC, LICENCE):
            with self.subTest(number=number):
                self.assertNotIn(
                    number,
                    body,
                    "a document number typed on the page must not be copied into the scan response",
                )

    def test_a_sensitive_control_still_reports_that_it_holds_a_value(self) -> None:
        # The value is dropped, the *fact that there is a value* is not. Without
        # this the panel could not tell the user "you have already filled this".
        result = scan(
            ScanRequest(url="", page_title="", fields=[field("Passport Number", name="passport_no", current_value=PASSPORT)])
        )
        row = result.fields[0]
        self.assertTrue(row.sensitive)
        self.assertTrue(row.already_filled)
        self.assertEqual(row.current_value, "")

    def test_every_document_number_spelling_is_recognised(self) -> None:
        for label in SENSITIVE_LABELS:
            with self.subTest(label=label):
                rows = normalise_fields([field(label, current_value="X0000000")])
                self.assertTrue(rows[0].sensitive, f"{label!r} must be treated as sensitive")
                self.assertEqual(rows[0].current_value, "")
                self.assertTrue(rows[0].sensitive_reason)

    def test_the_scan_reports_how_many_were_skipped_and_why(self) -> None:
        result = scan(
            ScanRequest(url="", page_title="", fields=sensitive_page())
        )
        self.assertEqual(result.counts.sensitive, 3)
        self.assertTrue(any("never generated, never transmitted" in note for note in result.notes))

    def test_institution_issued_ids_are_not_treated_as_documents(self) -> None:
        # The absolute rule is about government documents. Over-blocking here
        # would suppress answers users routinely need on an application form.
        for label in ["Student ID", "Application ID", "Candidate Reference Number", "Employee Number"]:
            with self.subTest(label=label):
                self.assertFalse(normalise_fields([field(label)])[0].sensitive)


class TestNothingSensitiveReachesTheModel(unittest.TestCase):
    """Section 5.1 at the network boundary - the one that matters most."""

    def test_no_document_number_reaches_any_prompt(self) -> None:
        client = StubClient({"webform": {}, "jd_analyze": {}})
        request = GenerateRequest(
            fields=sensitive_page() + [field("Cover letter", tag="textarea", type="textarea")],
            authorised_modules=list(ALL_MODULES),
            profile=PROFILE,
            jd_text=JD_TEXT,
            condition="C",
        )
        generate(request, client=client, kb_provider=StubKbProvider(None))

        self.assertTrue(client.calls, "the stub should have been called for the fillable fields")
        for call in client.calls:
            for number in (PASSPORT, NRIC, LICENCE):
                with self.subTest(task=call["task"], number=number):
                    self.assertNotIn(number, call["user"])
                    self.assertNotIn(number, call["system"])

    def test_a_sensitive_field_is_absent_from_the_field_list(self) -> None:
        client = StubClient({"webform": {}, "jd_analyze": {}})
        request = GenerateRequest(
            fields=sensitive_page(),
            authorised_modules=list(ALL_MODULES),
            profile=PROFILE,
            jd_text=JD_TEXT,
            condition="C",
        )
        generate(request, client=client, kb_provider=StubKbProvider(None))
        prompts = "\n".join(call["user"] for call in client.calls)
        self.assertIn("Full name", prompts)
        self.assertNotIn("passport", prompts.lower())
        self.assertNotIn("NRIC", prompts)
        self.assertNotIn("licence", prompts.lower())

    def test_a_document_number_typed_by_the_user_never_enters_the_prompt_either(self) -> None:
        # The user could paste a passport number into the free-text "additional
        # information" box. That field is fillable, so it IS sent to the model -
        # this test records that boundary honestly rather than claiming a
        # protection that does not exist.
        client = StubClient({"webform": {}, "jd_analyze": {}})
        request = GenerateRequest(
            fields=[field("Additional information", tag="textarea", type="textarea", current_value=f"Passport {PASSPORT}")],
            authorised_modules=list(ALL_MODULES),
            profile=PROFILE,
            jd_text=JD_TEXT,
            condition="C",
        )
        generate(request, client=client, kb_provider=StubKbProvider(None))
        prompts = "\n".join(call["user"] for call in client.calls)
        # The *field's current value* is not included in the field list at all -
        # only its label - so the number still does not reach the model.
        self.assertNotIn(PASSPORT, prompts)


class TestGenerateNeverOffers(unittest.TestCase):
    """Section 5.1 at the response boundary."""

    def _generate(self, response: dict | None = None):
        fields = sensitive_page()
        ids = {row.label: row.field_id for row in normalise_fields(fields)}
        payload = webform_payload(
            {
                ids["Passport Number"]: {"value": PASSPORT, "confidence": 0.99},
                ids["NRIC"]: {"value": NRIC, "confidence": 0.99},
                ids["Driving Licence Number"]: {"value": LICENCE, "confidence": 0.99},
                ids["Full name"]: {"value": "Zhang Wei", "confidence": 0.99},
            }
        )
        request = GenerateRequest(
            fields=fields,
            authorised_modules=list(ALL_MODULES),
            profile=PROFILE,
            jd_text=JD_TEXT,
            condition="C",
        )
        return generate(
            request,
            client=StubClient({"webform": payload if response is None else response, "jd_analyze": {}}),
            kb_provider=StubKbProvider(None),
        )

    def test_no_sensitive_field_gets_a_suggested_value(self) -> None:
        result = self._generate()
        for row in result.fields:
            if row.sensitive_skipped:
                with self.subTest(label=row.label):
                    self.assertIsNone(row.suggested_value)

    def test_the_whole_response_is_free_of_document_numbers(self) -> None:
        result = self._generate()
        body = result.model_dump_json()
        for number in (PASSPORT, NRIC, LICENCE):
            with self.subTest(number=number):
                self.assertNotIn(number, body)

    def test_each_sensitive_field_gets_the_same_plain_instruction(self) -> None:
        result = self._generate()
        skipped = [row for row in result.fields if row.sensitive_skipped]
        self.assertEqual(len(skipped), 3)
        for row in skipped:
            with self.subTest(label=row.label):
                self.assertEqual(row.message, MSG_SENSITIVE)
                self.assertEqual(row.confidence, 0.0)
                self.assertTrue(row.needs_user_confirmation)
                self.assertIsNone(row.suggested_value)

    def test_a_sensitive_field_is_not_counted_as_withheld_or_missing(self) -> None:
        # Three different states must stay distinguishable in the counts, or the
        # panel's summary lies about why a field is empty.
        result = self._generate()
        self.assertEqual(result.counts.sensitive_skipped, 3)
        self.assertEqual(result.counts.withheld_low_confidence, 0)
        self.assertEqual(result.counts.missing, 0)

    def test_a_sensitive_field_is_not_in_the_response_even_when_the_model_answers_it(self) -> None:
        # Belt and braces: the field is excluded from the prompt, so a well-behaved
        # model cannot answer it - but a model is not trusted to behave, so the
        # response must discard an entry for it too.
        result = self._generate()
        passport = next(row for row in result.fields if row.label == "Passport Number")
        self.assertIsNone(passport.suggested_value)


class TestTheClientCannotSmuggle(unittest.TestCase):
    """A hostile or buggy client must not be able to widen the assistant's reach."""

    def client(self) -> TestClient:
        return TestClient(create_app(require_token=True, token=TOKEN))

    def test_the_endpoint_requires_a_token_before_doing_anything(self) -> None:
        response = self.client().post(
            "/generate",
            json={"fields": [f.model_dump() for f in sensitive_page()], "authorised_modules": ["personal_info"]},
        )
        self.assertEqual(response.status_code, 401)

    def test_a_sensitive_field_sent_with_a_value_is_still_refused(self) -> None:
        # The rule is enforced server-side, so a client that sends the number
        # itself gains nothing.
        body = {
            "fields": [f.model_dump() for f in sensitive_page()],
            "authorised_modules": list(ALL_MODULES),
            "profile": PROFILE,
            "jd_text": JD_TEXT,
            "condition": "A",
        }
        response = self.client().post("/generate", json=body, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for number in (PASSPORT, NRIC, LICENCE):
            self.assertNotIn(number, json.dumps(payload))

    def test_the_scan_endpoint_never_returns_the_number_it_was_sent(self) -> None:
        body = {
            "url": "https://example.test/apply",
            "page_title": "Apply",
            "fields": [f.model_dump() for f in sensitive_page()],
        }
        response = self.client().post("/scan", json=body, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        for number in (PASSPORT, NRIC, LICENCE):
            self.assertNotIn(number, response.text)

    def test_an_undocumented_field_is_treated_as_unknown_not_guessed(self) -> None:
        # A field the classifier does not know must not be matched to the nearest
        # fact. "Favourite colour" is not "location".
        row = normalise_fields([field("Favourite colour")])[0]
        self.assertEqual(row.category, "unknown")
        self.assertIsNone(row.fact_key)


class TestNothingIsFabricated(unittest.TestCase):
    """Section 5.2: an offer is always one of the profile's own strings."""

    def test_every_offered_value_is_literally_in_the_authorised_profile(self) -> None:
        # The strongest available check: enumerate what the profile says, then
        # require every offered value to be one of those strings (or a prefix of
        # one, when the control had a length limit).
        fields = [
            field("Full name", name="full_name"),
            field("Email", name="email", type="email"),
            field("Phone", name="phone"),
            field("University", name="school"),
            field("Degree", name="degree"),
            field("Major", name="major"),
            field("Company name", name="employer"),
            field("Job title", name="title"),
            field("Project name", name="project"),
            field("Top skills", name="skills"),
            field("GPA", name="gpa"),
            field("Favourite colour", name="colour"),
            field("Desired salary", name="salary"),
        ]
        request = GenerateRequest(
            fields=fields,
            authorised_modules=list(ALL_MODULES),
            profile=PROFILE,
            jd_text=JD_TEXT,
            condition="A",
        )
        result = generate(request, client=StubClient({}), kb_provider=StubKbProvider(None))

        offered = [row for row in result.fields if row.suggested_value is not None]
        self.assertTrue(offered, "condition A should still answer the plain facts")
        for row in offered:
            with self.subTest(label=row.label):
                value = row.suggested_value or ""
                self.assertTrue(
                    any(value in fact or fact.startswith(value) for fact in PROFILE_FACTS),
                    f"{row.label!r} offered {value!r}, which is not in the profile",
                )

    def test_a_field_the_profile_cannot_answer_is_reported_not_guessed(self) -> None:
        result = generate(
            GenerateRequest(
                fields=[field("Desired salary", name="salary"), field("Favourite colour", name="colour")],
                authorised_modules=list(ALL_MODULES),
                profile=PROFILE,
                jd_text=JD_TEXT,
                condition="A",
            ),
            client=StubClient({}),
            kb_provider=StubKbProvider(None),
        )
        for row in result.fields:
            with self.subTest(label=row.label):
                self.assertIsNone(row.suggested_value)
                self.assertTrue(row.missing)
                self.assertTrue(row.message, "a missing field must say so in words")

    def test_an_unanswered_field_makes_the_counts_reconcilable(self) -> None:
        result = generate(
            GenerateRequest(
                fields=[
                    field("Full name", name="full_name"),
                    field("Desired salary", name="salary"),
                ],
                authorised_modules=list(ALL_MODULES),
                profile=PROFILE,
                jd_text=JD_TEXT,
                condition="A",
            ),
            client=StubClient({}),
            kb_provider=StubKbProvider(None),
        )
        counts = result.counts
        self.assertEqual(counts.total, 2)
        self.assertEqual(counts.suggestion_offered, 1)
        self.assertEqual(counts.missing, 1)
        # Every field is in exactly one of the five states, so the totals add up
        # and the panel's summary cannot quietly drop a field.
        self.assertEqual(
            counts.suggestion_offered
            + counts.withheld_low_confidence
            + counts.missing
            + counts.sensitive_skipped
            + counts.not_fillable,
            counts.total,
        )

    def test_withheld_and_missing_are_never_both_set(self) -> None:
        # `abstained` means the confidence rule withheld a candidate; `missing`
        # means there was no candidate. Seeding `abstained` from the raw
        # assessment made a field with nothing to offer count as "withheld for
        # weak evidence" as well - and so count twice.
        result = generate(
            GenerateRequest(
                fields=[
                    field("Desired salary", name="salary"),
                    field("Favourite colour", name="colour"),
                ],
                authorised_modules=list(ALL_MODULES),
                profile=PROFILE,
                jd_text=JD_TEXT,
                condition="A",
            ),
            client=StubClient({}),
            kb_provider=StubKbProvider(None),
        )
        for row in result.fields:
            with self.subTest(label=row.label):
                self.assertTrue(row.missing)
                self.assertFalse(row.abstained)
                self.assertFalse(row.missing and row.abstained)

    def test_an_extra_fact_key_in_the_profile_cannot_invent_a_value(self) -> None:
        # A user-defined key the extractor does not know is rendered to the model
        # (so it can be used) but never becomes a deterministic fact, so it cannot
        # be offered under another field's name.
        profile = {"personal_info": dict(PROFILE["personal_info"], secret_salary_expectation="999999")}
        rendered = render_profile(profile, ["personal_info"])
        facts = extract_facts(profile, ["personal_info"], rendered, jd_text=JD_TEXT)
        self.assertNotIn("secret_salary_expectation", facts)
        for fact in facts.values():
            with self.subTest(key=fact.key):
                self.assertNotIn("999999", fact.value)

    def test_the_offered_value_is_never_a_concatenation_of_two_facts(self) -> None:
        # A plausible failure mode for a generative step: blending the school and
        # the degree into a string that appears in neither.
        result = generate(
            GenerateRequest(
                fields=[field("University", name="school")],
                authorised_modules=list(ALL_MODULES),
                profile=PROFILE,
                jd_text=JD_TEXT,
                condition="A",
            ),
            client=StubClient({}),
            kb_provider=StubKbProvider(None),
        )
        value = result.fields[0].suggested_value or ""
        self.assertNotIn("Master of Science in Computer Science, Nanyang", value)
        self.assertEqual(value, "Nanyang Technological University")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
