#!/usr/bin/env python3
"""Session scoping for the shared TDD gate predicate, and its anti-disarm suite.

`tdd_check.find_last_test_signal` backs all three gates (Stop, TeammateIdle,
TaskCompleted). It scans the event log in reverse with no boundary, so a failure
recorded in an OLD session kept gating new ones even after the tree was clean.

The dangerous direction here is not the false positive — it is DISARMING. Every
narrowing below is paired with a control proving a real failure still blocks;
`TestGateStillBlocks` exists so that "the gate still has teeth" cannot break
silently.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import task_completed
import tdd_stop_gate
import teammate_idle
from conftest import (
    _HookTestCase,
    _make_stop_input,
    _make_task_completed_input,
    _make_teammate_idle_input,
    failing_tests_concern,
    make_event,
    passing_tests_status,
)
from event_schema import EVENT_TYPE_SESSION_STARTED, EVENT_TYPE_STATUS


def session_anchor() -> dict:
    """The boundary event. Emitted on startup/clear only — NOT on resume or
    compact, so compaction cannot reset the window and disarm the gate."""
    return make_event(EVENT_TYPE_SESSION_STARTED, content="Session started")


def filler(n: int) -> list[dict]:
    """Events carrying no test signal at all."""
    return [make_event(EVENT_TYPE_STATUS, content=f"Edited file {i}") for i in range(n)]


class _GateTestCase(_HookTestCase):
    """Drives the Stop gate with a mocked working tree."""

    def _stop(self, events: list[dict], *, dirty: bool) -> str | None:
        self._write_events(events)
        uncommitted = ["src/app.py"] if dirty else []
        with patch("commits.get_uncommitted_files", return_value=uncommitted) as mock:
            result = tdd_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.tree_was_checked = mock.called
        return result


class TestSessionScope(_GateTestCase):
    def test_prior_session_failure_clean_tree_does_not_block(self):
        """AC3. Nothing is broken in the tree and no test has run this session —
        the gate has nothing to say."""
        events = [failing_tests_concern(), session_anchor(), *filler(3)]
        self.assertIsNone(self._stop(events, dirty=False))

    def test_prior_session_failure_dirty_tree_still_blocks(self):
        """AC3's qualifier (customer decision). A red suite plus uncommitted
        broken code is still broken. Disarming is the dangerous direction, so
        the failure only stops gating once the tree is clean."""
        events = [failing_tests_concern(), session_anchor(), *filler(3)]
        self.assertIsNotNone(self._stop(events, dirty=True))

    def test_tree_is_not_consulted_for_an_in_session_failure(self):
        """The tree check is the rare path — reached only when the failure lies
        OUTSIDE the window. An in-session failure blocks on its own evidence."""
        self._stop([session_anchor(), failing_tests_concern()], dirty=False)
        self.assertFalse(self.tree_was_checked)

    def test_prior_fail_then_prior_pass_dirty_tree_does_not_block(self):
        """ONE unified reverse scan, not two.

        A passing status has no effect on any gate EXCEPT to short-circuit the
        reverse scan before an older unresolved failure is reached — and that
        short-circuit is the only non-resolution mechanism by which a later
        green run un-gates an earlier red one. Scoping the scan as two passes
        would make {prior FAIL, later prior PASS, dirty tree} newly block,
        reintroducing the very false positive this story kills.
        """
        events = [
            failing_tests_concern(),
            passing_tests_status(),
            session_anchor(),
            *filler(3),
        ]
        self.assertIsNone(self._stop(events, dirty=True))

    def test_resolved_prior_failure_does_not_block(self):
        """Resolution still wins regardless of window or tree."""
        fail = failing_tests_concern()
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Test concern resolved",
            metadata={"resolves": [fail["id"]]},
        )
        events = [fail, resolution, session_anchor(), *filler(3)]
        self.assertIsNone(self._stop(events, dirty=True))


class TestGateStillBlocks(_GateTestCase):
    """Anti-disarm controls. Each pins a way the narrowing could silently
    remove the gate's teeth. If one of these goes green-by-not-blocking, the
    gate is broken even though the suite would otherwise pass."""

    def test_in_session_failure_still_blocks(self):
        """AC2. The fix must not disarm the gate for a real failing run."""
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_no_anchor_scans_whole_log_and_blocks(self):
        """E3, the 200-event tail-cap trap. `_common.current_session_start_index`
        falls back to `len(events) - 200` when no anchor exists — a TAIL CAP,
        not a session boundary. Using it would silently stop blocking a genuine
        failure older than 200 events. With no anchor we scan EVERYTHING.
        """
        events = [*filler(5), failing_tests_concern(), *filler(300)]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_failure_at_the_window_edge_still_blocks(self):
        """Off-by-one: a failure recorded immediately after the anchor is
        in-session and must block."""
        events = [session_anchor(), failing_tests_concern()]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_teammate_idle_inherits_the_fix(self):
        """AC4. Fixed at the source — the sibling gates need no code change."""
        clean = [failing_tests_concern(), session_anchor(), *filler(3)]
        self._write_events(clean)
        with patch("commits.get_uncommitted_files", return_value=[]):
            self.assertIsNone(
                teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
            )

        self._write_events([session_anchor(), failing_tests_concern()])
        with patch("commits.get_uncommitted_files", return_value=[]):
            self.assertIsNotNone(
                teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
            )

    def test_task_completed_inherits_the_fix(self):
        """AC4, the other sibling gate."""
        clean = [failing_tests_concern(), session_anchor(), *filler(3)]
        self._write_events(clean)
        with patch("commits.get_uncommitted_files", return_value=[]):
            self.assertIsNone(
                task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
            )

        self._write_events([session_anchor(), failing_tests_concern()])
        with patch("commits.get_uncommitted_files", return_value=[]):
            self.assertIsNotNone(
                task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
            )


if __name__ == "__main__":
    unittest.main()
