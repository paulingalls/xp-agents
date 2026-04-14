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
        self.assertEqual(result["max_consecutive_test_failures"], 0)
        self.assertEqual(result["max_events_to_commit"], 0)

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

    def test_max_events_to_commit(self):
        """Events from first code change to next commit."""
        import work_signals

        events = [
            make_event("commit", content="First commit"),
            make_event("status", content="Wrote to a.py", working_on=["a.py"]),
            make_event("status", content="Tests passed", working_on=[]),
            make_event("commit", content="Second commit"),
        ]
        result = work_signals.build_work_signals(events)
        # 2 events: the edit + the test status
        self.assertEqual(result["max_events_to_commit"], 2)

    def test_max_events_picks_longest_gap(self):
        """Reports the longest edit-to-commit gap across all cycles."""
        import work_signals

        events = [
            make_event("status", working_on=["a.py"]),
            make_event("commit", content="Quick commit"),
            make_event("status", working_on=["b.py"]),
            make_event("status", content="Concern raised"),
            make_event("status", content="Tests passed", working_on=[]),
            make_event("commit", content="Slow commit"),
        ]
        result = work_signals.build_work_signals(events)
        # First cycle: 1 event. Second cycle: 3 events.
        self.assertEqual(result["max_events_to_commit"], 3)

    def test_no_code_changes_gap_is_zero(self):
        """No code changes (no working_on files) means gap is 0."""
        import work_signals

        events = [
            make_event("concern", content="Some concern"),
            make_event("decision", content="Use REST", topic="api"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 0)

    def test_planning_events_before_first_edit_excluded(self):
        """Events without working_on before first edit don't count."""
        import work_signals

        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api"),
            make_event("status", working_on=["a.py"]),
            make_event("commit", content="First commit"),
        ]
        result = work_signals.build_work_signals(events)
        # 1 event (the edit), NOT 3 (goal + decision + edit)
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_non_code_files_dont_start_gap(self):
        """Writes to .json/.md files don't trigger the gap counter."""
        import work_signals

        events = [
            make_event(
                "status",
                content="Wrote to sprint.json",
                working_on=["sprint.json"],
            ),
            make_event(
                "status",
                content="Wrote to plan.md",
                working_on=["plan.md"],
            ),
            make_event("status", content="Some hook status", working_on=[]),
            make_event("status", content="Some hook status", working_on=[]),
            make_event(
                "status",
                content="Wrote to auth.py",
                working_on=["scripts/auth.py"],
            ),
            make_event("commit", content="Add auth"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_code_file_starts_gap(self):
        """Writes to .py/.ts files do trigger the gap counter."""
        import work_signals

        events = [
            make_event(
                "status",
                content="Wrote to auth.py",
                working_on=["scripts/auth.py"],
            ),
            make_event("status", content="Some status", working_on=[]),
            make_event("status", content="Some status", working_on=[]),
            make_event("commit", content="Add auth"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 3)


if __name__ == "__main__":
    unittest.main()
