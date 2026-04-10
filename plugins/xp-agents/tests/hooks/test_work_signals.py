#!/usr/bin/env python3
"""Tests for work_signals.py — work analysis signals for retrospectives."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event


class TestWorkSignals(unittest.TestCase):
    """Tests for _build_work_signals sequence analysis."""

    def test_empty_events(self):
        import work_signals

        result = work_signals.build_work_signals([])
        self.assertEqual(result["concerns_addressed_by_commits"], 0)
        self.assertEqual(result["unaddressed_concerns"], 0)
        self.assertEqual(result["decisions_without_commits"], 0)
        self.assertEqual(result["max_consecutive_test_failures"], 0)
        self.assertEqual(result["max_events_between_commits"], 0)

    def test_concern_then_commit_counts(self):
        """Concern followed by a commit = addressed (Courage)."""
        import work_signals

        events = [
            make_event("concern", content="Missing error handling"),
            make_event("commit", content="Add error handling to API"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 1)
        self.assertEqual(result["unaddressed_concerns"], 0)

    def test_concern_without_commit_not_counted(self):
        """Concern at end of session with no subsequent commit."""
        import work_signals

        events = [
            make_event("commit", content="Initial work"),
            make_event("concern", content="Missing tests"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 0)
        self.assertEqual(result["unaddressed_concerns"], 1)

    def test_multiple_concerns_one_commit(self):
        """Multiple concerns before one commit — all addressed."""
        import work_signals

        events = [
            make_event("concern", content="Issue A"),
            make_event("concern", content="Issue B"),
            make_event("commit", content="Fix both issues"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 2)
        self.assertEqual(result["unaddressed_concerns"], 0)

    def test_decision_without_commit(self):
        """Decision with no subsequent commit = unimplemented."""
        import work_signals

        events = [
            make_event("decision", content="Use REST API", topic="api"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["decisions_without_commits"], 1)

    def test_decision_with_commit(self):
        """Decision followed by commit = implemented."""
        import work_signals

        events = [
            make_event("decision", content="Use REST API", topic="api"),
            make_event("commit", content="Add REST endpoint"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["decisions_without_commits"], 0)

    def test_max_consecutive_failures_three_reds(self):
        """red→red→red→green = 3 consecutive failures."""
        import work_signals

        events = [
            make_event("status", content="Tests: 10 passed, 2 failed (unittest)"),
            make_event("status", content="Tests: 11 passed, 1 failed (unittest)"),
            make_event("status", content="Tests: 10 passed, 3 failed (unittest)"),
            make_event("status", content="Tests: 13 passed, 0 failed (unittest)"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 3)

    def test_single_red_green_is_one(self):
        """One failure then pass = 1, normal TDD."""
        import work_signals

        events = [
            make_event("status", content="Tests: 10 passed, 1 failed (unittest)"),
            make_event("status", content="Tests: 11 passed, 0 failed (unittest)"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 1)

    def test_all_green_is_zero(self):
        """No failures = 0."""
        import work_signals

        events = [
            make_event("status", content="Tests: 10 passed, 0 failed (unittest)"),
            make_event("status", content="Tests: 11 passed, 0 failed (unittest)"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 0)

    def test_max_events_between_commits(self):
        """Longest gap between commits."""
        import work_signals

        events = [
            make_event("commit", content="First commit"),
            make_event("status", content="Wrote to a.py"),
            make_event("status", content="Wrote to b.py"),
            make_event("status", content="Tests: 5 passed, 0 failed (unittest)"),
            make_event("commit", content="Second commit"),
            make_event("status", content="Wrote to c.py"),
            make_event("commit", content="Third commit"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_between_commits"], 3)

    def test_no_commits_gap_is_zero(self):
        """No commits means gap is 0 (nothing to measure between)."""
        import work_signals

        events = [
            make_event("status", content="Wrote to a.py"),
            make_event("concern", content="Some concern"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_between_commits"], 0)


if __name__ == "__main__":
    unittest.main()
