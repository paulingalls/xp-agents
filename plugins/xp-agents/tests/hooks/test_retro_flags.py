#!/usr/bin/env python3
"""Tests for retro_flags: deterministic threshold evaluation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import retro_flags


def _healthy_signals():
    """Return signal dicts where no flags should fire."""
    honesty = {
        "max_unique_files_without_test": 2,
        "commits_without_triage": 0,
        "total_commits": 3,
        "code_commits": 3,
        "code_file_writes": 5,
        "concerns_raised": 2,
        "assumptions_stated": 3,
        "planning_events": 1,
    }
    work = {
        "concerns_addressed_by_commits": 2,
        "unaddressed_concerns": 0,
        "max_consecutive_test_failures": 1,
        "max_events_to_commit": 30,
    }
    status = {
        "quality_reviews": 3,
    }
    session = {
        "concerns_raised": 4,
        "concerns_resolved": 4,
        "questions_open": 0,
        "decisions_total": 2,
    }
    return honesty, work, status, session


class TestNoFlags(unittest.TestCase):
    def test_healthy_signals_produce_no_flags(self):
        flags = retro_flags.evaluate_flags(*_healthy_signals())
        self.assertEqual(flags, [])


class TestTDDStreak(unittest.TestCase):
    def test_fires_at_threshold(self):
        h, w, s, ss = _healthy_signals()
        h["max_unique_files_without_test"] = 5
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("max_unique_files_without_test", names)

    def test_below_threshold(self):
        h, w, s, ss = _healthy_signals()
        h["max_unique_files_without_test"] = 4
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_unique_files_without_test", names)


class TestCommitsWithoutTriage(unittest.TestCase):
    def test_fires_when_nonzero(self):
        h, w, s, ss = _healthy_signals()
        h["commits_without_triage"] = 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("commits_without_triage", names)


class TestWritesWithoutConcerns(unittest.TestCase):
    def test_fires_at_threshold(self):
        h, w, s, ss = _healthy_signals()
        h["code_file_writes"] = 10
        h["concerns_raised"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("writes_without_concerns", names)

    def test_no_flag_when_concerns_exist(self):
        h, w, s, ss = _healthy_signals()
        h["code_file_writes"] = 15
        h["concerns_raised"] = 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("writes_without_concerns", names)


class TestPlanningWithoutAssumptions(unittest.TestCase):
    def test_fires_when_planning_but_no_assumptions(self):
        h, w, s, ss = _healthy_signals()
        h["planning_events"] = 1
        h["assumptions_stated"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("planning_without_assumptions", names)

    def test_no_flag_without_planning(self):
        h, w, s, ss = _healthy_signals()
        h["planning_events"] = 0
        h["assumptions_stated"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("planning_without_assumptions", names)


class TestPlanningWithoutDecisions(unittest.TestCase):
    def test_fires_when_planning_but_no_decisions(self):
        h, w, s, ss = _healthy_signals()
        h["planning_events"] = 1
        ss["decisions_total"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("planning_without_decisions", names)

    def test_no_flag_without_planning(self):
        h, w, s, ss = _healthy_signals()
        h["planning_events"] = 0
        ss["decisions_total"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("planning_without_decisions", names)


class TestConcernsNotAddressed(unittest.TestCase):
    def test_fires_when_concerns_raised_but_none_addressed(self):
        h, w, s, ss = _healthy_signals()
        h["concerns_raised"] = 5
        w["concerns_addressed_by_commits"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("concerns_not_addressed", names)

    def test_no_flag_when_no_concerns(self):
        h, w, s, ss = _healthy_signals()
        h["concerns_raised"] = 0
        w["concerns_addressed_by_commits"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("concerns_not_addressed", names)


class TestUnaddressedConcerns(unittest.TestCase):
    def test_fires_when_nonzero(self):
        h, w, s, ss = _healthy_signals()
        w["unaddressed_concerns"] = 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("unaddressed_concerns", names)


class TestEventsToCommit(unittest.TestCase):
    def test_fires_at_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 50
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("max_events_to_commit", names)

    def test_below_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 49
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_events_to_commit", names)


class TestConsecutiveTestFailures(unittest.TestCase):
    def test_fires_at_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_consecutive_test_failures"] = 3
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("max_consecutive_test_failures", names)

    def test_below_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_consecutive_test_failures"] = 2
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_consecutive_test_failures", names)


class TestUnresolvedConcerns(unittest.TestCase):
    def test_fires_when_gap_exceeds_threshold(self):
        h, w, s, ss = _healthy_signals()
        ss["concerns_raised"] = 10
        ss["concerns_resolved"] = 5
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("unresolved_concerns", names)

    def test_no_flag_within_threshold(self):
        h, w, s, ss = _healthy_signals()
        ss["concerns_raised"] = 10
        ss["concerns_resolved"] = 8
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("unresolved_concerns", names)


class TestQuestionsOpen(unittest.TestCase):
    def test_fires_when_nonzero(self):
        h, w, s, ss = _healthy_signals()
        ss["questions_open"] = 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("questions_open", names)


class TestQualityReviews(unittest.TestCase):
    def test_fires_when_reviews_less_than_commits(self):
        h, w, s, ss = _healthy_signals()
        h["code_commits"] = 3
        s["quality_reviews"] = 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("quality_reviews_missing", names)

    def test_no_flag_when_no_code_commits(self):
        h, w, s, ss = _healthy_signals()
        h["code_commits"] = 0
        s["quality_reviews"] = 0
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("quality_reviews_missing", names)


class TestFlagStructure(unittest.TestCase):
    def test_flag_has_required_fields(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        self.assertTrue(len(flags) >= 1)
        flag = flags[0]
        for field in (
            "metric",
            "value",
            "threshold",
            "category",
            "xp_value",
            "message",
        ):
            self.assertIn(field, flag, f"Missing field: {field}")

    def test_category_is_fix(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        self.assertEqual(flags[0]["category"], "fix")


if __name__ == "__main__":
    unittest.main()
