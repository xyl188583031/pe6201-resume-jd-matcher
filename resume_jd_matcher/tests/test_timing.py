"""Tests for the gated timing metric.

The gate is the whole point: the instructor feedback said the single-timer
version was invalid, so the code must REFUSE to produce a number rather than
produce a bad one. These tests assert the refusal as hard as they assert the
computation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.timing import evaluate_timing  # noqa: E402


def row(timer, case, phase, minutes, exposure="baseline_first"):
    return {
        "timer_id": timer,
        "case_id": case,
        "phase": phase,
        "minutes": str(minutes),
        "first_exposure": exposure,
    }


class TestGate(unittest.TestCase):
    def test_no_data_is_not_reportable(self):
        result = evaluate_timing([], min_timers=3)
        self.assertFalse(result.reportable)
        self.assertEqual(result.status, "no_data")
        self.assertEqual(result.means, {})

    def test_single_timer_is_refused(self):
        """The exact failure the instructor flagged: one person, both phases."""
        rows = [row("me", "c1", "baseline", 30), row("me", "c1", "assisted", 15)]
        result = evaluate_timing(rows, min_timers=3)
        self.assertFalse(result.reportable)
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.n_timers, 1)
        self.assertIn("3 independent timers", result.reason)
        self.assertEqual(result.means, {}, "no number may be produced below the gate")

    def test_two_timers_is_still_refused(self):
        rows = [
            row("a", "c1", "baseline", 30), row("a", "c1", "assisted", 15),
            row("b", "c1", "baseline", 28), row("b", "c1", "assisted", 14),
        ]
        self.assertFalse(evaluate_timing(rows, min_timers=3).reportable)

    def test_three_timers_reports(self):
        rows = [
            row("a", "c1", "baseline", 30), row("a", "c1", "assisted", 15),
            row("b", "c1", "baseline", 40), row("b", "c1", "assisted", 20),
            row("c", "c1", "baseline", 20), row("c", "c1", "assisted", 10),
        ]
        result = evaluate_timing(rows, min_timers=3, target_reduction=0.30)
        self.assertTrue(result.reportable)
        self.assertEqual(result.status, "reported")
        self.assertEqual(result.n_timers, 3)
        self.assertEqual(result.counts["paired_cases"], 3)
        self.assertEqual(result.counts["cases_meeting_target"], 3)
        self.assertAlmostEqual(result.means["mean_reduction"], 0.50, places=6)

    def test_unpaired_measurements_are_not_counted(self):
        rows = [
            row("a", "c1", "baseline", 30), row("a", "c1", "assisted", 15),
            row("b", "c1", "baseline", 40), row("b", "c1", "assisted", 20),
            row("c", "c1", "baseline", 20),
            row("c", "c2", "assisted", 10),  # different case, no baseline
        ]
        result = evaluate_timing(rows, min_timers=3)
        self.assertTrue(result.reportable)
        self.assertEqual(result.counts["paired_cases"], 2)


class TestQualityFlags(unittest.TestCase):
    def test_order_contamination_is_flagged(self):
        rows = [
            row("a", "c1", "baseline", 30), row("a", "c1", "assisted", 15),
            row("b", "c1", "baseline", 40), row("b", "c1", "assisted", 20),
            row("c", "c1", "baseline", 20, exposure="assisted_first"),
            row("c", "c1", "assisted", 10, exposure="assisted_first"),
        ]
        result = evaluate_timing(rows, min_timers=3)
        self.assertTrue(result.reportable)
        self.assertTrue(any("contaminated" in w for w in result.warnings))

    def test_invalid_rows_are_ignored_not_crashed_on(self):
        rows = [
            row("a", "c1", "baseline", 30), row("a", "c1", "assisted", 15),
            row("b", "c1", "baseline", 40), row("b", "c1", "assisted", 20),
            row("c", "c1", "baseline", 20), row("c", "c1", "assisted", 10),
            {"timer_id": "", "case_id": "c1", "phase": "baseline", "minutes": "5"},
            {"timer_id": "d", "case_id": "c1", "phase": "nonsense", "minutes": "5"},
            {"timer_id": "e", "case_id": "c1", "phase": "baseline", "minutes": "abc"},
            {"timer_id": "f", "case_id": "c1", "phase": "baseline", "minutes": "-3"},
        ]
        result = evaluate_timing(rows, min_timers=3)
        self.assertTrue(result.reportable)
        self.assertEqual(result.n_timers, 3)


if __name__ == "__main__":
    unittest.main()
