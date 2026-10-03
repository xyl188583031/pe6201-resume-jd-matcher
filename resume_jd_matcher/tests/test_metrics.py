"""Scoring tests.

The metrics are the deliverable. If these are wrong, the report is wrong and
nothing upstream catches it, so each rule is pinned here with a hand-built case
where the expected answer can be checked by eye.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation import metrics as M  # noqa: E402


def make_gt(**overrides) -> M.GroundTruth:
    base = dict(
        case_id="case-1",
        job_family="AI/ML",
        variant="v01",
        jd_required_skills=["Python", "SQL", "MLOps"],
        candidate_skills=["Python", "SQL", "Docker"],
        expected_prefill={
            "full_name": "Tan Wei Ling",
            "email": "tan.weiling@example.edu",
            "education_school": "Nanyang Technological University",
            "top_skills": "Python|SQL|Docker",
        },
        skill_overlap=0.67,
        hard_case=False,
        should_abstain=False,
        expected_top_skills_n=2,
    )
    base.update(overrides)
    return M.GroundTruth(**base)


def make_record(**overrides) -> dict:
    base = {
        "condition": "C",
        "abstained": False,
        "match_score": 67,
        "confidence": 0.71,
        "jd_skills": ["Python", "SQL", "MLOps"],
        "top_skills": ["Python", "SQL"],
        "claimed_items": ["Python", "SQL"],
        "retrieved_chunk_ids": ["onet_aiml_01"],
        "prefill": {
            "full_name": "Tan Wei Ling",
            "email": "tan.weiling@example.edu",
            "education_school": "Nanyang Technological University",
            "top_skills": "Python, SQL",
        },
        "errors": [],
    }
    base.update(overrides)
    return base


class TestCoverage(unittest.TestCase):
    def test_full_coverage(self):
        score = M.score_case(make_record(), make_gt())
        self.assertTrue(score.complete_coverage)
        self.assertAlmostEqual(score.coverage, 1.0)

    def test_partial_coverage_when_implied_requirement_missed(self):
        """Condition A's structural blind spot: MLOps is implied, not named."""
        record = make_record(jd_skills=["Python", "SQL"])
        score = M.score_case(record, make_gt())
        self.assertFalse(score.complete_coverage)
        self.assertAlmostEqual(score.coverage, 2 / 3, places=6)

    def test_extra_extracted_skill_does_not_break_complete_coverage(self):
        record = make_record(jd_skills=["Python", "SQL", "MLOps", "Docker"])
        score = M.score_case(record, make_gt())
        self.assertTrue(score.complete_coverage)

    def test_empty_required_set_scores_zero_not_one(self):
        record = make_record(jd_skills=["Python"])
        score = M.score_case(record, make_gt(jd_required_skills=[]))
        self.assertEqual(score.coverage, 0.0)
        self.assertFalse(score.complete_coverage)


class TestFabrication(unittest.TestCase):
    def test_clean_case(self):
        score = M.score_case(make_record(), make_gt())
        self.assertTrue(score.zero_fabrication)
        self.assertEqual(score.fabricated, [])

    def test_invented_match_skill_is_caught(self):
        record = make_record(claimed_items=["Python", "Kubernetes"])
        score = M.score_case(record, make_gt())
        self.assertFalse(score.zero_fabrication)
        self.assertEqual(score.fabricated, ["Kubernetes"])
        self.assertFalse(score.passed)

    def test_invented_prefill_skill_is_caught(self):
        """A fabrication in the prefill output counts too, not only in the report."""
        record = make_record(top_skills=["Python", "Terraform"])
        score = M.score_case(record, make_gt())
        self.assertIn("Terraform", score.fabricated)

    def test_casing_and_punctuation_do_not_hide_a_fabrication(self):
        record = make_record(claimed_items=["  kubernetes  "])
        score = M.score_case(record, make_gt())
        self.assertEqual(score.fabricated, ["Kubernetes"])


class TestPrefillMatch(unittest.TestCase):
    def test_all_four_fields_exact(self):
        score = M.score_case(make_record(), make_gt())
        self.assertTrue(score.prefill_all_match)

    def test_top_skills_is_a_subset_rule_not_equality(self):
        """The pool has three skills; returning any two of them is correct."""
        gt = make_gt(expected_prefill={**make_gt().expected_prefill,
                                       "top_skills": "Docker|Python|SQL"})
        record = make_record(prefill={**make_record()["prefill"], "top_skills": "SQL, Docker"})
        score = M.score_case(record, gt)
        self.assertTrue(score.prefill_match["top_skills"])

    def test_top_skills_wrong_count_fails(self):
        record = make_record(prefill={**make_record()["prefill"], "top_skills": "Python"})
        score = M.score_case(record, make_gt())
        self.assertFalse(score.prefill_match["top_skills"])

    def test_top_skills_outside_the_pool_fails(self):
        record = make_record(prefill={**make_record()["prefill"], "top_skills": "Python, Rust"})
        score = M.score_case(record, make_gt())
        self.assertFalse(score.prefill_match["top_skills"])

    def test_email_case_folding(self):
        record = make_record(
            prefill={**make_record()["prefill"], "email": "Tan.WeiLing@example.edu"}
        )
        score = M.score_case(record, make_gt())
        self.assertTrue(score.prefill_match["email"])

    def test_blank_output_fails_every_field(self):
        record = make_record(
            prefill={"full_name": "", "email": "", "education_school": "", "top_skills": ""}
        )
        score = M.score_case(record, make_gt())
        self.assertFalse(score.prefill_all_match)


class TestPassBar(unittest.TestCase):
    def test_abstained_case_cannot_pass(self):
        """It delivers nothing, so it cannot satisfy 'outputs suggestions that...'.

        The prefill is deliberately POPULATED. The first version of this test
        left the four fields empty, so it went green because the fields were
        empty rather than because the case had abstained - which is exactly how
        the defect it was written to catch stayed live. A regression test for an
        abstention rule has to abstain while carrying correct-looking output.
        """
        record = make_record(abstained=True)
        score = M.score_case(record, make_gt())
        self.assertTrue(score.prefill_all_match)   # the four fields all agree ...
        self.assertTrue(score.zero_fabrication)    # ... and nothing is invented ...
        self.assertTrue(score.abstained)           # ... but the case was declined
        self.assertFalse(score.passed)

    def test_abstained_case_with_populated_prefill_is_not_a_pass(self):
        """The delivered-run shape: A's PM-v05 and C's SE-v04 both looked like this."""
        for condition in ("A", "C"):
            with self.subTest(condition=condition):
                record = make_record(condition=condition, abstained=True)
                score = M.score_case(record, make_gt())
                self.assertFalse(score.passed)
                self.assertFalse(score.abstained and score.passed)

    def test_condition_metrics_counts(self):
        gt = {
            "a": make_gt(),
            "b": make_gt(),
            "c": make_gt(),
        }
        records = [
            {**make_record(), "case_id": "a"},
            {**make_record(), "case_id": "b", "claimed_items": ["Kubernetes"]},
            {
                **make_record(),
                "case_id": "c",
                "abstained": True,
                "prefill": {"full_name": "", "email": "", "education_school": "", "top_skills": ""},
            },
        ]
        scores = M.score_run(records, gt)
        built = M.build_condition_metrics("C", "RAG-enhanced", scores, pass_bar_fraction=0.8)
        self.assertEqual(built.n_cases, 3)
        self.assertEqual(built.counts["passed"], 1)
        self.assertEqual(built.counts["zero_fabrication"], 2)
        self.assertEqual(built.counts["abstained"], 1)
        self.assertEqual(built.fmt("passed"), "1/3")
        # 0.8 * 3 rounds to 2, so one passing case is below the bar
        self.assertEqual(built.counts["passed"] < 2, True)


class TestGroundTruthLoading(unittest.TestCase):
    def test_shipped_ground_truth_parses_and_is_consistent(self):
        path = REPO_ROOT / "data" / "cases" / "ground_truth.csv"
        if not path.exists():
            self.skipTest("ground truth not generated yet")
        gt = M.load_ground_truth(path)
        cases = (REPO_ROOT / "data" / "cases" / "cases.json")
        self.assertTrue(gt, "ground truth is empty")
        for case_id, row in gt.items():
            with self.subTest(case=case_id):
                self.assertTrue(row.jd_required_skills)
                self.assertTrue(row.candidate_skills)
                self.assertTrue(row.expected_prefill["full_name"])
                self.assertTrue(row.expected_prefill["email"])
                named = set(M._skill_set(row.jd_required_skills))
                # hard_case must follow the stated definition, not a hand-set flag
                self.assertEqual(row.hard_case, row.skill_overlap < 0.5)
                self.assertEqual(row.should_abstain, row.hard_case)
                self.assertTrue(named)


if __name__ == "__main__":
    unittest.main()
