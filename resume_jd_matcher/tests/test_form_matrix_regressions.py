"""Regression tests for the real defects the form matrix found.

Rounds 2 and 3 of the browser-assistant test work. Each test names the finding it
pins, so a reader can move from the test to the evidence and back:

    test_legend_never_names_a_field            -> artifacts/form_matrix/report.md §5 row 1
    test_readonly_control_is_not_fillable      -> artifacts/form_matrix/report.md §5 row 2
    test_a_readonly_control_gets_no_value      -> artifacts/form_matrix/report.md §5 row 2
    test_disabled_control_is_not_fillable      -> artifacts/form_matrix/report.md §5 row 3
    test_experience_facts_are_not_tailored     -> artifacts/form_matrix/report.md §5 row 4
    test_missing_reason_names_the_absent_fact  -> artifacts/form_matrix/report.md §5 row 5

`§5 row N` is the Nth row of the report's section 5 table. Rows 4 and 5 are the
two findings the round-2 L2 sheet named `7a` and `7b`, which is how the change
log and `l2_review.md` refer to them.

Every defect had the same shape: something the system was not entitled to treat
as evidence *was* treated as evidence, and the system then acted on it
confidently. A section heading acted as a field's name; a locked value was read
and a replacement offered; a disabled control was offered a value the page could
never submit; a fact about the person was scored as if it were an answer
tailored to the posting; and a missing fact was explained by a retrieval score
that had never been computed for it.

The tests assert behaviour, not implementation. Where a fixture pair matters -
the cross-domain profile against the cross-domain posting - it is loaded from
`data/test_matrix/`, the same files `scripts/run_form_matrix.py` feeds the
matrix, so a test and the report row it cites cannot drift apart.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.field_map import classify, normalise_fields  # noqa: E402
from server.schemas import GenerateRequest, RawField  # noqa: E402
from server.services import (  # noqa: E402
    FACT_CATEGORIES,
    TAILORED_CATEGORIES,
    RetrievalContext,
    _evidence_for_field,
    generate,
)
from tests.server_fixtures import (  # noqa: E402
    ALL_MODULES,
    JD_TEXT,
    PROFILE,
    StubClient,
    StubKnowledgeBase,
    StubKbProvider,
    field,
)

#: The pair the section 5 rows 4 / 5 findings were measured on: a business
#: analytics graduate against a coastal-survey posting, whose measured retrieval
#: score is 0.0 and whose profile deliberately declares no GPA.
_MATRIX_DIR = REPO_ROOT / "data" / "test_matrix"
CROSS_DOMAIN_PROFILE: dict[str, Any] = json.loads(
    (_MATRIX_DIR / "resumes" / "cross_domain_profile.json").read_text(encoding="utf-8")
)["profile"]
CROSS_DOMAIN_JD: str = json.loads(
    (_MATRIX_DIR / "jds" / "jd_cross_domain.json").read_text(encoding="utf-8")
)["text"]


def decide(
    raw_fields: list[RawField],
    *,
    profile: dict[str, Any] | None = None,
    jd_text: str = JD_TEXT,
    kb_score: float = 0.85,
    condition: str = "C",
):
    """Run the real `generate()` with stub collaborators, offline.

    Defaults describe the ordinary case - the test profile, an in-domain posting,
    a knowledge base that retrieves something. The round-3 tests deliberately
    leave those defaults: `kb_score=0.0` is how a posting with no relationship to
    the knowledge base is reproduced, and it is the condition the abstention rule
    is about.
    """
    stub = StubClient({"webform": {}, "jd_analyze": {}})
    provider = StubKbProvider(StubKnowledgeBase(score=kb_score))
    request = GenerateRequest(
        fields=raw_fields,
        authorised_modules=list(ALL_MODULES),
        profile=profile if profile is not None else PROFILE,
        jd_text=jd_text,
        condition=condition,
    )
    return generate(request, client=stub, kb_provider=provider, run_id="regression-test")


def result_id_of(raw: RawField) -> str:
    """The field id the server will derive for this control."""
    return normalise_fields([raw])[0].field_id


class TestSectionTextIsNeverAFieldName(unittest.TestCase):
    """report.md §5 row 1 - the `label` side of README bug 19."""

    #: The legend the form_03 shape uses. It matches *both* the candidate-name
    #: pattern (`applicant name`) and the employer pattern (`employer`), which is
    #: exactly why it must not be allowed to act as a field's name: if it did,
    #: both controls under it would land in the same category.
    LEGEND = "Applicant name and employer details"

    def test_legend_never_names_a_field(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 1.

        form_03 puts a candidate-name control and an employer control under the
        same `<fieldset>` legend. Before this fix the legend reached the
        classifier as the field's *name* through the nearby-text rule, the
        generic `\\bname\\b` fallback won for both, and the assistant offered the
        candidate's full name into the employer box.

        Two controls in one section must land in different categories, and the
        one that is named only by its section must be refused rather than filled
        with the other one's fact.
        """
        candidate, employer = normalise_fields(
            [
                # Names itself: an explicit <label>.
                field(
                    "Applicant name",
                    name="applicant_name",
                    id="applicant_name",
                    section_context=self.LEGEND,
                ),
                # Names itself: nothing at all. Only the section says what it is.
                field("Name", name="name_2", id="name_2", section_context=self.LEGEND),
            ]
        )

        self.assertEqual(candidate.category, "personal")
        self.assertEqual(candidate.fact_key, "full_name")

        self.assertNotEqual(
            employer.category,
            candidate.category,
            "two controls in one section must not collapse onto one category",
        )
        self.assertIsNone(employer.fact_key)
        self.assertEqual(employer.category, "unknown")

    def test_the_section_context_is_what_suppresses_the_fallback(self) -> None:
        # The mechanism, isolated: the same control, with and without the
        # section. Without it the fallback still fires, which is the behaviour
        # every other form depends on.
        alone = field("Name", name="name_2", id="name_2", section_context="")
        self.assertEqual(classify(alone)[2], "full_name")

        in_employer_section = field(
            "Name", name="name_2", id="name_2", section_context=self.LEGEND
        )
        self.assertIsNone(classify(in_employer_section)[2])

    def test_a_section_never_reclassifies_a_control_that_names_itself(self) -> None:
        # Guard against the obvious over-correction: putting the section text
        # *into* the classified text would let one legend override every label
        # inside it - "Company name" under "Employer details" would stop being an
        # employer field at all. The context may veto a guess; it may not vote.
        self.assertEqual(
            classify(
                field("Company name", name="employer", section_context=self.LEGEND)
            )[2],
            "internship_employer",
        )
        self.assertEqual(
            classify(field("Job title", name="job_title", section_context=self.LEGEND))[2],
            "internship_title",
        )


class TestReadonlyControls(unittest.TestCase):
    """report.md §5 row 2 - a locked control was treated as fillable."""

    def test_readonly_control_is_not_fillable(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 2.

        form_05 marks an email input `readonly` and gives it a label that maps
        onto a profile fact, so the classifier produced a value - `decision:
        offered` for a control the page had locked. The DOM does *not* stop a
        script assigning `.value` to a readonly input, which is exactly why the
        rule has to be explicit.
        """
        locked = normalise_fields(
            [field("Email address (locked)", name="email_readonly", type="email", readonly=True)]
        )[0]
        self.assertFalse(locked.fillable)
        self.assertIn("readonly", locked.skip_reason)
        self.assertFalse(locked.already_filled)

        # The same control without the attribute is still ordinary, so the rule
        # cannot be satisfied by refusing everything.
        ordinary = normalise_fields(
            [field("Email address", name="email", type="email")]
        )[0]
        self.assertTrue(ordinary.fillable)
        self.assertEqual(ordinary.fact_key, "email")

    def test_a_readonly_control_gets_no_value(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 2.

        At the level the report counts: the row's decision. The matrix derives
        `not_fillable` from `fillable is False`, and hashes `suggested_value`;
        an empty hash is the "no value behind this decision" assertion.
        """
        result = decide(
            [
                field(
                    "Email address (locked)",
                    name="email_readonly",
                    type="email",
                    readonly=True,
                    current_value="",
                )
            ]
        )
        row = result.fields[0]
        self.assertFalse(row.fillable)
        self.assertIsNone(row.suggested_value, "a locked control must carry no value")
        self.assertFalse(row.already_filled)
        self.assertFalse(row.missing, "refused is not the same as unanswered")
        self.assertEqual(row.message, row.message.strip())
        self.assertIn("readonly", row.message)

    def test_a_readonly_control_is_not_the_only_thing_refused(self) -> None:
        # Ordering: a locked *password* box is still reported as a password box,
        # because that is the more specific and more dangerous fact. The readonly
        # rule must not swallow the type-based refusals.
        locked_password = normalise_fields(
            [field("Portal password", name="portal_password", type="password", readonly=True)]
        )[0]
        self.assertFalse(locked_password.fillable)
        self.assertIn("password", locked_password.skip_reason)
        self.assertNotIn("readonly", locked_password.skip_reason)

    def test_a_locked_value_is_not_carried_across_the_boundary(self) -> None:
        # What the browser sends is already blank (the content script never reads
        # a locked value). If a caller sends one anyway, the server drops it - the
        # same treatment a document number gets, and for the same reason: a value
        # the user can never edit is not ours to pass around.
        locked = normalise_fields(
            [
                field(
                    "Email address (locked)",
                    name="email_readonly",
                    type="email",
                    readonly=True,
                    current_value="someone@example.edu",
                )
            ]
        )[0]
        self.assertEqual(locked.current_value, "")
        self.assertNotIn("someone@example.edu", locked.model_dump_json())

    def test_a_readonly_select_is_left_alone_by_this_rule(self) -> None:
        # `readonly` is not a valid attribute on a <select>, so the rule must not
        # invent a refusal for one. It is still reported and still fillable.
        chosen = normalise_fields(
            [field("Degree", tag="select", type="select", options=["BSc", "MSc"], readonly=True)]
        )[0]
        self.assertTrue(chosen.fillable)


class TestDisabledControls(unittest.TestCase):
    """report.md §5 row 3 - the `readonly` family, found one round later.

    Same shape as `TestReadonlyControls`, deliberately: a control the page has
    switched off was treated as fillable, and the DOM would not have stopped the
    write. `disabled` is refused at both layers, and - because a control can be
    both disabled and something worse - the type-based refusals still win.
    """

    def test_disabled_control_is_not_fillable(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 3.

        form_05 carries an email input marked `disabled` whose label maps onto a
        profile fact, so the classifier produces a fact key for it and would
        otherwise offer a value the page can neither edit nor submit. The DOM does
        not stop a script assigning `.value` to a disabled input either, which is
        exactly why the rule has to be explicit rather than inferred.
        """
        locked = normalise_fields(
            [
                field(
                    "Email address (disabled)",
                    name="email_disabled",
                    type="email",
                    disabled=True,
                )
            ]
        )[0]
        self.assertFalse(locked.fillable)
        self.assertIn("disabled", locked.skip_reason)
        self.assertFalse(locked.already_filled)
        # The label still classifies - the refusal is about the control, not about
        # the classifier failing to understand it. That distinction is the whole
        # reason `not_fillable` and `missing` are separate decisions.
        self.assertEqual(locked.fact_key, "email")

        # The same control without the attribute is still ordinary, so the rule
        # cannot be satisfied by refusing everything.
        ordinary = normalise_fields([field("Email address", name="email", type="email")])[0]
        self.assertTrue(ordinary.fillable)
        self.assertEqual(ordinary.fact_key, "email")

    def test_a_disabled_control_gets_no_value(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 3.

        At the level the report counts. The matrix derives `not_fillable` from
        `fillable is False` and hashes `suggested_value`; an absent value is the
        "no value behind this decision" assertion, and `missing is False` is what
        separates "refused" from "unanswered".
        """
        row = decide(
            [
                field(
                    "Email address (disabled)",
                    name="email_disabled",
                    type="email",
                    disabled=True,
                    current_value="",
                )
            ],
            kb_score=0.0,
        ).fields[0]
        self.assertFalse(row.fillable)
        self.assertIsNone(row.suggested_value, "a disabled control must carry no value")
        self.assertFalse(row.missing, "refused is not the same as unanswered")
        self.assertFalse(row.abstained)
        self.assertFalse(row.already_filled)
        self.assertIn("disabled", row.message)

    def test_type_refusals_still_win_over_disabled(self) -> None:
        # Ordering, and the reason `disabled` is described as a second line of
        # defence rather than the first: a disabled *password* box is still
        # reported as a password box, because that is the more specific and more
        # dangerous fact. A refusal rule that swallowed the type rules would be a
        # regression dressed as a fix.
        locked_password = normalise_fields(
            [field("Portal password", name="portal_password", type="password", disabled=True)]
        )[0]
        self.assertFalse(locked_password.fillable)
        self.assertIn("password", locked_password.skip_reason)
        self.assertNotIn("disabled", locked_password.skip_reason)

    def test_a_disabled_value_is_not_carried_across_the_boundary(self) -> None:
        # What the browser sends is already blank (the content script never reads
        # a disabled value). If a caller sends one anyway the server drops it - the
        # same treatment a locked value gets, and for the same reason: a value the
        # user can never edit is not ours to pass around.
        locked = normalise_fields(
            [
                field(
                    "Email address (disabled)",
                    name="email_disabled",
                    type="email",
                    disabled=True,
                    current_value="someone@example.edu",
                )
            ]
        )[0]
        self.assertEqual(locked.current_value, "")
        self.assertNotIn("someone@example.edu", locked.model_dump_json())

    def test_disabled_is_refused_on_every_control_shape(self) -> None:
        # `disabled` is valid on <input>, <textarea> and <select>. The matrix
        # plants the input shape only, so the other two are pinned here rather
        # than left to be discovered by a form that happens to use them.
        for kwargs in (
            {"tag": "select", "type": "select", "options": ["BSc", "MSc"]},
            {"tag": "textarea", "type": "textarea"},
        ):
            with self.subTest(tag=kwargs["tag"]):
                row = normalise_fields(
                    [field("Degree", name="degree", disabled=True, **kwargs)]
                )[0]
                self.assertFalse(row.fillable)
                self.assertIn("disabled", row.skip_reason)


class TestExperienceFactsAreNotTailored(unittest.TestCase):
    """report.md §5 row 4 - a fact about the person was scored as a tailored answer.

    `services._evidence_for_field` gives a posting-tailored field the posting's
    retrieval score. That is right for a summary, wrong for an employer's name -
    and when the posting retrieves nothing the difference is the whole answer.
    """

    #: The four fact-shaped sub-fields, and the two narrative sub-fields they were
    #: split away from. Labels and names are the ones `demo/form_matrix/`
    #: `form_01_baseline.html` uses, so this table describes the tested page.
    FACT_SUB_FIELDS = {
        "Company name": ("experience_fact", "internship_employer"),
        "Job title": ("experience_fact", "internship_title"),
        "Internship period": ("experience_fact", "internship_dates"),
        "Project name": ("project_fact", "project_name"),
    }
    NARRATIVE_SUB_FIELDS = ("Describe your internship", "Project description")

    def test_experience_facts_are_not_tailored(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 4 (finding 7a).

        On `cross_domain_profile` against `jd_cross_domain` the retrieval score is
        0.0 - a posting with no relationship to the knowledge base. The profile
        plainly states the employer and the job title. Before the split both
        controls sat in the `experience` category, inherited that zero, and
        `0.6 * 0.0 + 0.4 * llm_self` fell under the 0.4 threshold, so they were
        withheld: the same field, on the same form, with the same source, was
        offered in the L-A cell and abstained in the L-C cell.
        """
        rows = decide(
            [
                field("Company name", name="employer"),
                field("Job title", name="job_title"),
            ],
            profile=CROSS_DOMAIN_PROFILE,
            jd_text=CROSS_DOMAIN_JD,
            kb_score=0.0,
        ).fields

        expected = {
            "Company name": ("Harbour Retail Group", "internship.internship_employer"),
            "Job title": ("Operations Intern", "internship.internship_title"),
        }
        for row in rows:
            with self.subTest(field=row.label):
                value, source = expected[row.label]
                self.assertFalse(
                    row.abstained,
                    "a fact the profile states must not be withheld because the posting "
                    "is unrelated",
                )
                self.assertFalse(row.missing)
                self.assertEqual(row.suggested_value, value)
                self.assertEqual(row.source, source)

    def test_the_four_fact_sub_fields_are_their_own_categories(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 4 (finding 7a).

        The split, asserted where it lives. `TAILORED_CATEGORIES` is the list that
        decides who inherits the posting's retrieval score, so membership of it is
        the decision this finding is about - not the wording of any message.
        """
        for label, (category, fact_key) in self.FACT_SUB_FIELDS.items():
            with self.subTest(field=label):
                got_category, _module, got_key = classify(
                    field(label, name=label.lower().replace(" ", "_"))
                )
                self.assertEqual(got_category, category)
                self.assertEqual(got_key, fact_key)
                self.assertIn(category, FACT_CATEGORIES)
                self.assertNotIn(
                    category,
                    TAILORED_CATEGORIES,
                    "a fact category must not inherit the posting's retrieval score",
                )

        for label in self.NARRATIVE_SUB_FIELDS:
            with self.subTest(field=label):
                category = classify(field(label, tag="textarea"))[0]
                self.assertIn(
                    category,
                    TAILORED_CATEGORIES,
                    "the narrative halves of experience / project stay tailored",
                )

    def test_a_tailored_field_still_abstains_on_the_same_pair(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 4 (finding 7a).

        The guard against over-correction, and the reason the fix is a split
        rather than a relaxation. Key skills genuinely has to be tailored to the
        posting; on this pair the retrieval score is 0.0, so it must still be
        withheld. A change that made the whole matrix stop abstaining would look
        like a fix on the count and be a much worse defect.
        """
        row = decide(
            [field("Key skills", name="skills")],
            profile=CROSS_DOMAIN_PROFILE,
            jd_text=CROSS_DOMAIN_JD,
            kb_score=0.0,
        ).fields[0]
        self.assertTrue(row.abstained)
        self.assertIsNone(row.suggested_value)

    def test_a_fact_is_offered_with_a_relevant_posting_too(self) -> None:
        # The other direction, so the fix cannot be satisfied by always offering:
        # with a posting the knowledge base does retrieve for, the same controls
        # are offered from the same source at the same confidence. Nothing about
        # the in-domain path changed.
        rows = decide(
            [
                field("Company name", name="employer"),
                field("Job title", name="job_title"),
            ],
            profile=CROSS_DOMAIN_PROFILE,
            kb_score=0.85,
        ).fields
        self.assertEqual(
            [row.suggested_value for row in rows],
            ["Harbour Retail Group", "Operations Intern"],
        )
        self.assertTrue(all(not row.abstained for row in rows))


class TestMissingReasonAttribution(unittest.TestCase):
    """report.md §5 row 5 - a missing fact was explained by a retrieval score.

    The decision was right and the explanation was wrong, which is why this
    finding moved no count: `missing` was already the outcome. What the user is
    told to go and fix is the part that had to change.
    """

    def test_missing_reason_names_the_absent_fact(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 5 (finding 7b).

        `cross_domain_profile` declares no GPA in its education block, and
        declares that absence on purpose. The control is correctly `missing`.
        Before the fix the reason read `retrieval similarity 0.00 < threshold
        0.40`, which points the user at the posting when the cause is the
        profile - and nothing had been retrieved *for that field*, so the number
        was never about it.
        """
        row = decide(
            [field("GPA", name="gpa")],
            profile=CROSS_DOMAIN_PROFILE,
            jd_text=CROSS_DOMAIN_JD,
            kb_score=0.0,
        ).fields[0]

        self.assertTrue(row.missing)
        self.assertIsNone(row.suggested_value)
        joined = "; ".join(row.reasons)
        self.assertNotIn("retrieval similarity", joined)
        self.assertIn("no fact in the authorised profile", joined)
        # And it does not quietly keep claiming a component it never measured.
        self.assertNotIn("retrieval", row.components_present)

    def test_an_absent_fact_contributes_no_evidence(self) -> None:
        """Source: artifacts/form_matrix/report.md §5 row 5 (finding 7b).

        The mechanism, isolated. `_evidence_for_field` fills the confidence
        formula's `retrieval` slot. For a fact category with no fact it must
        return nothing at all, while an `unknown` control on the *same* retrieval
        still gets the retrieved score - so this is a scoped change, not the
        retrieval path being switched off.
        """
        gpa = normalise_fields([field("GPA", name="gpa")])[0]
        colour = normalise_fields([field("Favourite colour", name="colour")])[0]
        strong = RetrievalContext(score=0.9, chunk_ids=["chunk_000"], notes=[])

        self.assertEqual(gpa.category, "education")
        self.assertEqual(colour.category, "unknown")

        self.assertIsNone(
            _evidence_for_field(gpa, condition="C", retrieval=strong, fact=None),
            "a fact field with no fact has no evidence, whatever retrieval returned",
        )
        self.assertEqual(
            _evidence_for_field(colour, condition="C", retrieval=strong, fact=None),
            0.9,
            "an unclassifiable control still uses the posting as its only weak signal",
        )

    def test_a_field_with_a_fact_keeps_the_ordinary_reason(self) -> None:
        # The guard against over-correction: the new reason must not replace the
        # normal ones on a field whose fact the profile *does* hold. An email
        # address on the same pair is still offered from the profile, with the
        # ordinary reason attached.
        row = decide(
            [field("Email", name="email", type="email")],
            profile=CROSS_DOMAIN_PROFILE,
            jd_text=CROSS_DOMAIN_JD,
            kb_score=0.0,
        ).fields[0]
        self.assertEqual(row.suggested_value, "nurul.hakim@example.com")
        self.assertNotIn("no fact in the authorised profile", "; ".join(row.reasons))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
