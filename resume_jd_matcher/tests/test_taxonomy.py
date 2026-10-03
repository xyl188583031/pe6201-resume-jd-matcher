"""Taxonomy tests.

The vocabulary is shared by the baseline, the stub and the fabrication check.
If it drifts, three things break at once and they break quietly.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.taxonomy import (  # noqa: E402
    SKILL_LEXICON,
    canonicalise,
    has_lexical_support,
    match_skills,
    ordered_skills,
    skill_overlap,
)

BANK = REPO_ROOT / "data" / "synthetic_generator" / "jd_bank.json"


class TestMatching(unittest.TestCase):
    def test_basic_detection(self):
        found = match_skills("We need Python and SQL experience with REST APIs.")
        self.assertIn("Python", found)
        self.assertIn("SQL", found)
        self.assertIn("REST APIs", found)

    def test_case_insensitive(self):
        self.assertIn("PyTorch", match_skills("pytorch and PYTORCH"))
        self.assertEqual(len(match_skills("pytorch")), 1)

    def test_word_boundaries_prevent_substring_false_positives(self):
        # "excellent" must not read as Excel; "digital" must not read as Git.
        found = match_skills("excellent communication and digital literacy")
        self.assertNotIn("Excel", found)
        self.assertNotIn("Git", found)

    def test_bare_go_is_not_a_technology(self):
        """A deliberate false-negative.

        Matching a standalone "go" found the verb far more often than the
        language, so Go is only recognised through "golang".
        """
        self.assertNotIn("Go", match_skills("we go to market quickly"))
        self.assertIn("Go", match_skills("golang services"))

    def test_bare_r_is_not_a_language(self):
        self.assertNotIn("R", match_skills("r and d team"))

    def test_credentials_are_not_skills(self):
        found = match_skills("Master of Science in Computer Science, PhD preferred")
        self.assertNotIn("Master Degree", found)
        self.assertNotIn("PhD", found)

    def test_acronym_and_expansion_both_detected(self):
        self.assertIn("RAG", match_skills("retrieval augmented generation"))
        self.assertIn("NLP", match_skills("Natural Language Processing"))

    def test_empty_input(self):
        self.assertEqual(match_skills(""), set())
        self.assertEqual(match_skills(None), set())  # type: ignore[arg-type]


class TestOverlap(unittest.TestCase):
    def test_overlap_fraction(self):
        self.assertAlmostEqual(skill_overlap({"Python", "SQL"}, {"Python", "SQL", "MLOps"}), 2 / 3)

    def test_empty_requirement_set_is_zero_not_one(self):
        self.assertEqual(skill_overlap({"Python"}, set()), 0.0)

    def test_ordering_follows_the_reference(self):
        self.assertEqual(
            ordered_skills({"SQL", "Python"}, ["Python", "SQL"]), ["Python", "SQL"]
        )


class TestCanonicalise(unittest.TestCase):
    def test_aliases_map_back(self):
        self.assertEqual(canonicalise("sklearn"), "scikit-learn")
        self.assertEqual(canonicalise("PyTorch"), "PyTorch")

    def test_unknown_value_passes_through_stripped(self):
        self.assertEqual(canonicalise("  Rust  "), "Rust")

    def test_skill_written_with_its_acronym_resolves(self):
        """One skill spelled twice must map to the skill, not stay unresolved.

        A real model answered `natural language processing (NLP)` for a resume
        that states it verbatim. The unresolved string was then counted as a
        fabrication, inflating the headline fabrication metric against a
        candidate who genuinely had the skill.
        """
        self.assertEqual(canonicalise("natural language processing (NLP)"), "NLP")
        self.assertEqual(canonicalise("Natural Language Processing (NLP)"), "NLP")

    def test_genuine_compound_is_left_verbatim(self):
        """Picking one half would under-report a real fabrication."""
        compound = "Machine Learning and Deep Learning"
        self.assertEqual(canonicalise(compound), compound)


class TestLexiconIntegrity(unittest.TestCase):
    def test_no_alias_maps_to_two_skills(self):
        seen: dict[str, str] = {}
        for skill, aliases in SKILL_LEXICON.items():
            for alias in aliases:
                key = alias.lower()
                self.assertNotIn(
                    key, seen, f"alias {alias!r} is claimed by {seen.get(key)!r} and {skill!r}"
                )
                seen[key] = skill

    @unittest.skipUnless(BANK.exists(), "jd_bank.json not present")
    def test_display_forms_round_trip(self):
        """The generator depends on this; a failure here means ground truth drifts."""
        bank = json.loads(BANK.read_text(encoding="utf-8"))
        for skill, display in bank["display"].items():
            with self.subTest(skill=skill):
                self.assertEqual(
                    match_skills(display),
                    {skill},
                    f"display {display!r} does not map back to exactly {skill!r}",
                )

    @unittest.skipUnless(BANK.exists(), "jd_bank.json not present")
    def test_every_family_skill_has_a_display_form(self):
        bank = json.loads(BANK.read_text(encoding="utf-8"))
        display = bank["display"]
        for family, spec in bank["families"].items():
            for skill in list(spec["core_skills"]) + list(spec.get("nice_to_have", [])):
                with self.subTest(family=family, skill=skill):
                    self.assertIn(skill, display)


class TestLexicalSupport(unittest.TestCase):
    """The fabrication guard's predicate.

    Regression cover for a live-only failure: the guard used a raw set
    difference between the model's skill strings and the canonical vocabulary.
    Real models answer in lower case, so every claim looked unsupported, the
    guard stripped the whole matched-skill list and capped confidence at
    `fabrication_cap` - forcing abstention on every case of every live run.
    The offline stub answers in canonical names, so the offline suite was green
    throughout.
    """

    RESUME = (
        "Skills: Python, PyTorch, Machine Learning, Feature Engineering, "
        "Model Evaluation, SQL, pandas, scikit-learn. Deployed with Spark jobs."
    )

    def test_lowercase_claim_is_supported(self):
        """The exact shape a real model returns."""
        self.assertTrue(has_lexical_support("machine learning", self.RESUME))
        self.assertTrue(has_lexical_support("feature engineering", self.RESUME))
        self.assertTrue(has_lexical_support("model evaluation", self.RESUME))

    def test_alias_claim_is_supported(self):
        self.assertTrue(has_lexical_support("sklearn", self.RESUME))

    def test_expansion_of_an_absent_acronym_is_not_supported(self):
        """The resume never mentions NLP, by acronym or by expansion."""
        self.assertFalse(has_lexical_support("NLP", self.RESUME))
        self.assertFalse(has_lexical_support("natural language processing", self.RESUME))

    def test_out_of_lexicon_skill_stated_literally_is_supported(self):
        """Spark is not in SKILL_LEXICON; the resume says it, so it counts."""
        self.assertTrue(has_lexical_support("Spark", self.RESUME))

    def test_genuinely_absent_skill_is_not_supported(self):
        """The half of the guard that must keep working."""
        self.assertFalse(has_lexical_support("TensorFlow", self.RESUME))
        self.assertFalse(has_lexical_support("Kubernetes", self.RESUME))

    def test_a_word_hiding_inside_another_word_is_not_support(self):
        """A real hallucination this guard initially waved through.

        A candidate listed JavaScript; the model claimed Java. The fallback's
        plain substring test matched "java" inside "javascript", so the guard
        reported the claim as supported and the fabrication reached the output.
        """
        self.assertEqual(match_skills("Python, JavaScript, Git, REST APIs, SQL, Excel"),
                         {"Python", "JavaScript", "Git", "REST APIs", "SQL", "Excel"})
        self.assertFalse(
            has_lexical_support("Java", "Python, JavaScript, Git, REST APIs, SQL, Excel")
        )
        # ...and the genuine article is still accepted when really present.
        self.assertTrue(has_lexical_support("Java", "Languages: Java, Kotlin, SQL"))
        self.assertTrue(has_lexical_support("JavaScript", "Python, JavaScript, Git"))

    def test_empty_claim_is_not_supported(self):
        self.assertFalse(has_lexical_support("", self.RESUME))
        self.assertFalse(has_lexical_support("   ", self.RESUME))

    def test_the_bug_that_this_replaced(self):
        """Pin the old behaviour as wrong, so a revert is caught."""
        claims = ["machine learning", "feature engineering", "model evaluation"]
        present = match_skills(self.RESUME)

        old_style = {c for c in claims} - present
        self.assertTrue(old_style, "the raw set difference is expected to misfire")
        self.assertGreaterEqual(len(old_style), 3)

        new_style = {
            canonicalise(c)
            for c in claims
            if not has_lexical_support(c, self.RESUME, present=present)
        }
        self.assertEqual(new_style, set())


if __name__ == "__main__":
    unittest.main()
