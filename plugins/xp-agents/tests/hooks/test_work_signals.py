#!/usr/bin/env python3
"""Tests for work_signals.py — work analysis signals for retrospectives."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_event, tests_run_status
from event_schema import (
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)
from test_parsing import PARSER_STATUS_FAILED


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
            make_event(EVENT_TYPE_CONCERN, content="Missing error handling"),
            make_event(EVENT_TYPE_COMMIT, content="Add error handling to API"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 1)
        self.assertEqual(result["unaddressed_concerns"], 0)

    def test_concern_without_commit_not_counted(self):
        """Concern at end of session with no subsequent commit."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_COMMIT, content="Initial work"),
            make_event(EVENT_TYPE_CONCERN, content="Missing tests"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 0)
        self.assertEqual(result["unaddressed_concerns"], 1)

    def test_multiple_concerns_one_commit(self):
        """Multiple concerns before one commit — all addressed."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_CONCERN, content="Issue A"),
            make_event(EVENT_TYPE_CONCERN, content="Issue B"),
            make_event(EVENT_TYPE_COMMIT, content="Fix both issues"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 2)
        self.assertEqual(result["unaddressed_concerns"], 0)

    def test_max_consecutive_failures_three_reds(self):
        """red→red→red→green = 3 consecutive failures."""
        import work_signals

        events = [
            tests_run_status(passed=False),
            tests_run_status(passed=False),
            tests_run_status(passed=False),
            tests_run_status(passed=True),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 3)

    def test_single_red_green_is_one(self):
        """One failure then pass = 1, normal TDD."""
        import work_signals

        events = [
            tests_run_status(passed=False),
            tests_run_status(passed=True),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 1)

    def test_all_green_is_zero(self):
        """No failures = 0."""
        import work_signals

        events = [
            tests_run_status(passed=True),
            tests_run_status(passed=True),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 0)

    def test_max_events_to_commit(self):
        """Events from first code change to next commit."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_COMMIT, content="First commit"),
            make_event(EVENT_TYPE_STATUS, content="Wrote to a.py", working_on=["a.py"]),
            make_event(EVENT_TYPE_STATUS, content="Tests passed", working_on=[]),
            make_event(EVENT_TYPE_COMMIT, content="Second commit"),
        ]
        result = work_signals.build_work_signals(events)
        # 2 events: the edit + the test status
        self.assertEqual(result["max_events_to_commit"], 2)

    def test_max_events_picks_longest_gap(self):
        """Reports the longest edit-to-commit gap across all cycles."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"]),
            make_event(EVENT_TYPE_COMMIT, content="Quick commit"),
            make_event(EVENT_TYPE_STATUS, working_on=["b.py"]),
            make_event(EVENT_TYPE_STATUS, content="Concern raised"),
            make_event(EVENT_TYPE_STATUS, content="Tests passed", working_on=[]),
            make_event(EVENT_TYPE_COMMIT, content="Slow commit"),
        ]
        result = work_signals.build_work_signals(events)
        # First cycle: 1 event. Second cycle: 3 events.
        self.assertEqual(result["max_events_to_commit"], 3)

    def test_no_code_changes_gap_is_zero(self):
        """No code changes (no working_on files) means gap is 0."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_CONCERN, content="Some concern"),
            make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 0)

    def test_planning_events_before_first_edit_excluded(self):
        """Events without working_on before first edit don't count."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_GOAL, content="Ship v1"),
            make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api"),
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"]),
            make_event(EVENT_TYPE_COMMIT, content="First commit"),
        ]
        result = work_signals.build_work_signals(events)
        # 1 event (the edit), NOT 3 (goal + decision + edit)
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_non_code_files_dont_start_gap(self):
        """Writes to .json/.md files don't trigger the gap counter."""
        import work_signals

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="Wrote to sprint.json",
                working_on=["sprint.json"],
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="Wrote to plan.md",
                working_on=["plan.md"],
            ),
            make_event(EVENT_TYPE_STATUS, content="Some hook status", working_on=[]),
            make_event(EVENT_TYPE_STATUS, content="Some hook status", working_on=[]),
            make_event(
                EVENT_TYPE_STATUS,
                content="Wrote to auth.py",
                working_on=["scripts/auth.py"],
            ),
            make_event(EVENT_TYPE_COMMIT, content="Add auth"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_code_file_starts_gap(self):
        """Writes to .py/.ts files do trigger the gap counter."""
        import work_signals

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="Wrote to auth.py",
                working_on=["scripts/auth.py"],
            ),
            make_event(EVENT_TYPE_STATUS, content="Some status", working_on=[]),
            make_event(EVENT_TYPE_STATUS, content="Some status", working_on=[]),
            make_event(EVENT_TYPE_COMMIT, content="Add auth"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 3)


class TestWorkSignalsM2Actions(unittest.TestCase):
    """sprint-042 M2: action-aware classification with regex fallback."""

    def test_test_run_action_failure_increments_consecutive_failures(self):
        """metadata.action=test_run_complete with test_passed=false counts
        as a failed test run, exactly like the legacy regex path."""
        import work_signals

        events = [
            make_event(
                EVENT_TYPE_STATUS,
                content="opaque",
                metadata={
                    "action": STATUS_ACTION_TEST_RUN_COMPLETE,
                    "test_passed": False,
                    "test_count": 1,
                    "framework": "pytest",
                },
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="opaque",
                metadata={
                    "action": STATUS_ACTION_TEST_RUN_COMPLETE,
                    "test_passed": False,
                    "test_count": 1,
                    "framework": "pytest",
                },
            ),
            make_event(
                EVENT_TYPE_STATUS,
                content="opaque",
                metadata={
                    "action": STATUS_ACTION_TEST_RUN_COMPLETE,
                    "test_passed": True,
                    "test_count": 5,
                    "framework": "pytest",
                },
            ),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_consecutive_test_failures"], 2)

    def test_parser_failed_run_does_not_reset_consecutive_failures(self):
        """A test_run_complete with parser_status=parser_failed carries no
        signal — must not break a red streak by green-washing 'don't know'."""
        import work_signals

        events = [
            tests_run_status(passed=False),
            tests_run_status(passed=False),
            tests_run_status(parser_status=PARSER_STATUS_FAILED),
            tests_run_status(passed=False),
        ]
        result = work_signals.build_work_signals(events)
        # Streak survives the parser_failed event: 3 reds in a row, not 2.
        self.assertEqual(result["max_consecutive_test_failures"], 3)

    def test_concern_then_type_commit_counts_addressed(self):
        """Real type=commit events (with metadata.action=commit_success) close
        pending concerns the same way legacy 'Committed:' status events did."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_CONCERN, content="Missing tests"),
            make_event(
                EVENT_TYPE_COMMIT,
                content="Add tests",
                files=["tests/foo.py"],
                metadata={"action": STATUS_ACTION_COMMIT_SUCCESS, "commit_hash": "abc"},
            ),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["concerns_addressed_by_commits"], 1)
        self.assertEqual(result["unaddressed_concerns"], 0)


if __name__ == "__main__":
    unittest.main()
