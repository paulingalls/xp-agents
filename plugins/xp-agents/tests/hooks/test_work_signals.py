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
    METADATA_KEY_TDD_RED,
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


class TestWorkSignalsBatchPartition(unittest.TestCase):
    """story-010: the batch counter must measure ONE agent's own work.

    Before this, a single global stream summed every agent's events, so the
    flag's advice ("commit more often") was unactionable — no single agent
    could shrink a counter fed by thirteen others.
    """

    def test_batch_is_partitioned_per_agent(self):
        """Interleaved agents are counted against their own agent_id."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"], agent_id="teammate-1"),
            make_event(EVENT_TYPE_STATUS, working_on=["b.py"], agent_id="teammate-2"),
            *[
                make_event(
                    EVENT_TYPE_STATUS,
                    content="more work",
                    working_on=[],
                    agent_id="teammate-2",
                )
                for _ in range(5)
            ],
            make_event(EVENT_TYPE_COMMIT, content="t1 commits", agent_id="teammate-1"),
            make_event(EVENT_TYPE_COMMIT, content="t2 commits", agent_id="teammate-2"),
        ]
        result = work_signals.build_work_signals(events)
        # teammate-1 batched 1 event (its own edit); teammate-2 batched 6.
        # Summed globally, teammate-1's commit would have closed a 7-event
        # interval it did not create.
        self.assertEqual(result["max_events_to_commit"], 6)

    def test_batch_names_the_agent_it_measured(self):
        """The max is attributed, so the reader knows whose batch to shrink."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"], agent_id="teammate-1"),
            make_event(EVENT_TYPE_COMMIT, content="quick", agent_id="teammate-1"),
            make_event(EVENT_TYPE_STATUS, working_on=["b.py"], agent_id="teammate-2"),
            make_event(
                EVENT_TYPE_STATUS, content="x", working_on=[], agent_id="teammate-2"
            ),
            make_event(EVENT_TYPE_COMMIT, content="slow", agent_id="teammate-2"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 2)
        self.assertEqual(result["max_events_to_commit_agent"], "teammate-2")

    def test_no_batch_leaves_agent_unnamed(self):
        """Nothing measured means nothing to attribute."""
        import work_signals

        result = work_signals.build_work_signals([])
        self.assertEqual(result["max_events_to_commit"], 0)
        self.assertIsNone(result["max_events_to_commit_agent"])

    def test_test_runs_excluded_from_batch(self):
        """test_run_complete is TDD-loop telemetry, not batched work."""
        import work_signals

        events = [
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"]),
            tests_run_status(passed=False),
            tests_run_status(passed=False),
            tests_run_status(passed=True),
            make_event(EVENT_TYPE_COMMIT, content="Green"),
        ]
        result = work_signals.build_work_signals(events)
        # 1 (the edit), not 4 — running tests three times is the Feedback
        # value working, and must not read as a bigger batch.
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_test_run_before_first_edit_does_not_anchor(self):
        """An excluded event cannot open the interval it is excluded from."""
        import work_signals

        events = [
            tests_run_status(passed=True),
            make_event(EVENT_TYPE_STATUS, working_on=["a.py"]),
            make_event(EVENT_TYPE_COMMIT, content="Commit"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 1)

    def test_edits_are_counted_as_the_batch(self):
        """Edits ARE the work being batched — they are not telemetry.

        Pins decision ff515bf71b6d against the discarded variant that also
        dropped file_write, under which this run would score 0 and AC-2
        (same edit volume, twice the commits) could not discriminate.
        """
        import work_signals

        events = [
            *[
                make_event(
                    EVENT_TYPE_STATUS,
                    content="Wrote a code file",
                    working_on=[f"src/mod_{i}.py"],
                    metadata={"action": "file_write"},
                )
                for i in range(6)
            ],
            make_event(EVENT_TYPE_COMMIT, content="One big batch"),
        ]
        result = work_signals.build_work_signals(events)
        self.assertEqual(result["max_events_to_commit"], 6)

    def test_committing_twice_as_often_scores_materially_lower(self):
        """AC-2, on the flag's own counter, at identical edit volume."""
        import work_signals

        def edits(n, start=0):
            return [
                make_event(
                    EVENT_TYPE_STATUS,
                    content="edit",
                    working_on=[f"src/mod_{i}.py"],
                    metadata={"action": "file_write"},
                )
                for i in range(start, start + n)
            ]

        commit = make_event(EVENT_TYPE_COMMIT, content="commit")
        rare = work_signals.build_work_signals([*edits(8), commit])
        often = work_signals.build_work_signals(
            [*edits(4), commit, *edits(4, start=4), commit]
        )
        self.assertEqual(rare["max_events_to_commit"], 8)
        self.assertEqual(often["max_events_to_commit"], 4)


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

    def test_tdd_red_run_does_not_increment_consecutive_failures(self):
        """A test_run_complete tagged metadata.tdd_red=True (prior commit
        was test-only — RED step in TDD cycle) is expected-failure noise,
        not regression signal. Skip it from the consecutive_failures
        counter so retros don't flag legitimate red TDD as a problem.
        Sprint-072 retro flagged 5 consecutive failures that were all
        red TDD steps — this prevents that misclassification.

        Sequence pins SKIP semantics, not RESET: red → tdd_red → red →
        green → max=2 (skip preserves the streak across the tdd_red).
        Reset semantics would yield max=1 — the test distinguishes the
        two behaviors (reviewer concern 7e575281624a).
        """
        import work_signals

        events = [
            tests_run_status(passed=False),
            tests_run_status(passed=False, metadata_extra={METADATA_KEY_TDD_RED: True}),
            tests_run_status(passed=False),
            tests_run_status(passed=True),
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
