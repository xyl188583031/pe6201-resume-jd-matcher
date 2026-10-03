"""Abstention rule tests.

These run with no model, no key and no network. The rule is the safety
mechanism of the whole product, so it is tested directly rather than inferred
from an offline run.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import ConfidenceConfig  # noqa: E402
from src.pipeline import confidence as conf  # noqa: E402

CFG = ConfidenceConfig(
    threshold=0.4,
    w_retrieval=0.6,
    w_llm_self=0.4,
    abstain_on_either=True,
    hard_case_overlap=0.5,
)


class TestCombination(unittest.TestCase):
    def test_weighted_mean_when_both_present(self):
        result = conf.assess(retrieval_similarity=0.8, llm_self_confidence=0.6, cfg=CFG)
        self.assertAlmostEqual(result.combined, 0.6 * 0.8 + 0.4 * 0.6, places=6)
        self.assertEqual(result.components_present, ["llm_self", "retrieval"])
        self.assertFalse(result.abstain)

    def test_missing_llm_component_uses_retrieval_alone(self):
        """Condition A has no model. Substituting 0.0 would abstain forever."""
        result = conf.assess(retrieval_similarity=0.9, llm_self_confidence=None, cfg=CFG)
        self.assertAlmostEqual(result.combined, 0.9, places=6)
        self.assertEqual(result.components_present, ["retrieval"])
        self.assertFalse(result.abstain)

    def test_missing_retrieval_component_uses_llm_alone(self):
        """Condition B has no retrieval. Same argument, opposite direction."""
        result = conf.assess(retrieval_similarity=None, llm_self_confidence=0.7, cfg=CFG)
        self.assertAlmostEqual(result.combined, 0.7, places=6)
        self.assertEqual(result.components_present, ["llm_self"])
        self.assertFalse(result.abstain)

    def test_no_components_declines(self):
        result = conf.assess(retrieval_similarity=None, llm_self_confidence=None, cfg=CFG)
        self.assertTrue(result.abstain)
        self.assertEqual(result.combined, 0.0)


class TestThreshold(unittest.TestCase):
    def test_below_threshold_abstains(self):
        result = conf.assess(retrieval_similarity=0.3, llm_self_confidence=0.3, cfg=CFG)
        self.assertAlmostEqual(result.combined, 0.3, places=6)
        self.assertTrue(result.abstain)
        self.assertTrue(any("combined confidence" in r for r in result.reasons))

    def test_exactly_at_threshold_does_not_abstain(self):
        """Strictly-below, per the Problem Statement: '< 0.4 -> decline'."""
        result = conf.assess(retrieval_similarity=0.4, llm_self_confidence=0.4, cfg=CFG)
        self.assertFalse(result.abstain)

    def test_high_combination_still_abstains_when_retrieval_weak(self):
        """The silent-failure guard (PS section 8, Risk 2).

        A confident model on top of bad retrieval is the dangerous case: the
        combined score can clear the threshold while the grounding is junk.
        """
        result = conf.assess(retrieval_similarity=0.1, llm_self_confidence=1.0, cfg=CFG)
        self.assertGreater(result.combined, 0.4)  # the average alone would pass
        self.assertTrue(result.abstain)           # the either-component rule catches it
        self.assertTrue(any("retrieval similarity" in r for r in result.reasons))

    def test_retrieval_can_rescue_a_timid_model(self):
        result = conf.assess(retrieval_similarity=1.0, llm_self_confidence=0.2, cfg=CFG)
        self.assertTrue(result.abstain)
        self.assertTrue(any("model self-confidence" in r for r in result.reasons))

    def test_either_rule_can_be_disabled(self):
        relaxed = ConfidenceConfig(
            threshold=0.4, w_retrieval=0.6, w_llm_self=0.4,
            abstain_on_either=False, hard_case_overlap=0.5,
        )
        result = conf.assess(retrieval_similarity=0.1, llm_self_confidence=1.0, cfg=relaxed)
        self.assertFalse(result.abstain)


class TestFieldLevelAndHardCases(unittest.TestCase):
    def test_field_abstention_is_per_field(self):
        verdicts = conf.field_level_abstentions(
            {"full_name": 0.9, "email": 0.95, "education_school": 0.2, "top_skills": 0.0},
            cfg=CFG,
        )
        self.assertFalse(verdicts["full_name"])
        self.assertTrue(verdicts["education_school"])
        self.assertTrue(verdicts["top_skills"])

    def test_hard_case_boundary(self):
        self.assertTrue(conf.is_hard_case(0.49, cfg=CFG))
        self.assertFalse(conf.is_hard_case(0.50, cfg=CFG))


if __name__ == "__main__":
    unittest.main()
