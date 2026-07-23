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

import _common
import bash_failure
import task_completed
import tdd_stop_gate
import teammate_idle
from _tdd_gate_fixtures import _GateTestCase, filler, session_anchor
from concerns import TEST_CONCERN_RE
from conftest import (
    _HookTestCase,
    _make_bash_failure_input,
    _make_stop_input,
    _make_task_completed_input,
    _make_teammate_idle_input,
    failing_tests_concern,
    make_event,
    passing_tests_status,
)
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_BASH_FAILED,
)

_WATERMARK_ID = "test-tdd-gate-session-scope"


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

    def test_unanswerable_git_still_blocks(self):
        """Absence of evidence is not evidence of a clean tree.

        The tree check is the ONLY thing keeping a prior-session failure
        gating, and this story's new untracked-file scan (`git ls-files
        --others`) walks the whole worktree — the call most likely to hit
        `_run_git`'s 5s timeout. A timeout that reads as CLEAN would un-gate a
        real failure, so `get_uncommitted_files` returns None for "git could
        not answer" and only a POSITIVE clean reading may un-gate.
        """
        events = [failing_tests_concern(), session_anchor(), *filler(3)]
        self._write_events(events)
        with patch("commits.get_uncommitted_files", return_value=None):
            self.assertIsNotNone(
                tdd_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
            )

    def test_gates_check_the_tree_at_the_hook_input_cwd(self):
        """The gate must consult the session's OWN tree.

        `cwd` from the hook input is this codebase's authoritative source; the
        process cwd is a documented leak. A teammate's Stop hook resolving to
        the wrong tree makes git answer nothing, which — before the fail-safe
        above — read as CLEAN. Pin that all three gates thread it through.
        """
        events = [failing_tests_concern(), session_anchor(), *filler(3)]
        self._write_events(events)
        for gate, make_input in (
            (tdd_stop_gate, _make_stop_input),
            (teammate_idle, _make_teammate_idle_input),
            (task_completed, _make_task_completed_input),
        ):
            with self.subTest(gate=gate.__name__):
                with patch(
                    "commits.get_uncommitted_files", return_value=[]
                ) as mock_tree:
                    # A LEAD session cwd (no `worktree-story-` segment) — the
                    # gates run for the lead and must thread this cwd into the
                    # tree check. A teammate-shaped cwd would (correctly) skip
                    # the gate outright, which is a different behavior.
                    gate.run(make_input(cwd="/wt/lead-session"), smm_dir=self.smm_dir)
                mock_tree.assert_called_once_with("/wt/lead-session")

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


_TEAMMATE_CWD = "/Users/dev/xp-agents/.claude/worktrees/worktree-story-003"
_LEAD_CWD = "/Users/dev/xp-agents"


class TestTeammateReaderWindow(_GateTestCase):
    """story-003: only the LEAD emits `session_started` (a teammate's
    session_start.run returns early, appending no anchor). A worktree
    teammate reading the lead's anchor as its own session boundary means a
    mid-sprint lead `/clear` — which appends a fresh anchor AFTER the
    teammate's still-live failure — reclassifies that failure as
    prior-session. A teammate that already committed its work has a clean
    tree, so the existing prior-session-plus-clean-tree bound would silently
    un-gate a genuinely red suite. A worktree teammate lives exactly one
    session, so its window must always start at 0, independent of any anchor
    the lead wrote.
    """

    def test_teammate_live_failure_before_lead_clear_anchor_still_blocks(self):
        """AC1. The failure predates the lead's mid-sprint /clear anchor, and
        the teammate's tree is clean (already committed) — the dangerous
        combination that would un-gate under the lead's anchor-relative
        window. The teammate has no prior session, so this must still
        block. The failure is the teammate's OWN (agent_id == its worktree
        name); a foreign one is covered in TestTeammateReaderAgentScope."""
        events = [
            failing_tests_concern(agent_id="worktree-story-003"),
            session_anchor(),
            *filler(3),
        ]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNotNone(result)
        self.assertIn("failing", str(result).lower())

    def test_lead_prior_session_clean_tree_bound_is_preserved(self):
        """AC2 control: the pre-existing lead-path bound (prior-session
        failure + clean tree -> un-gated) must be untouched. Detection is
        cwd-only, so this holds regardless of the suite's own process cwd."""
        events = [failing_tests_concern(), session_anchor(), *filler(3)]
        result = self._stop(events, cwd=_LEAD_CWD, dirty=False)
        self.assertIsNone(result)

    def test_teammate_no_anchor_scans_whole_log_not_a_tail_cap(self):
        """AC3, teammate reader. No anchor exists yet; the teammate window
        is 0 either way, but must not degrade into a tail cap."""
        events = [
            *filler(5),
            failing_tests_concern(agent_id="worktree-story-003"),
            *filler(300),
        ]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNotNone(result)


class TestTeammateReaderAgentScope(_GateTestCase):
    """Regression #2: a worktree teammate shares events.jsonl with the lead
    and every sibling teammate, and its window is always 0 (it lives one
    session). Scoping by time alone made it gate on ANY unresolved
    failing-test concern in the shared log — including one authored by the
    lead or a sibling, which this teammate cannot see or fix. Its gate must
    consider only its OWN signals (agent_id == its worktree name). The lead
    reader keeps its whole-session, un-scoped behaviour."""

    def test_sibling_fail_concern_does_not_block_the_teammate(self):
        # Authored by a SIBLING teammate; read by worktree-story-003, clean tree.
        events = [failing_tests_concern(agent_id="worktree-story-007"), *filler(3)]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNone(result)

    def test_lead_fail_concern_does_not_block_the_teammate(self):
        events = [failing_tests_concern(agent_id="main"), *filler(3)]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNone(result)

    def test_own_fail_concern_still_blocks_the_teammate(self):
        # Control: the teammate's OWN unresolved failure still gates it.
        events = [failing_tests_concern(agent_id="worktree-story-003"), *filler(3)]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNotNone(result)

    def test_sibling_pass_does_not_un_gate_the_teammates_own_failure(self):
        # A sibling's later green run must not short-circuit this teammate's
        # own earlier unresolved failure.
        events = [
            failing_tests_concern(agent_id="worktree-story-003"),
            passing_tests_status(agent_id="worktree-story-007"),
            *filler(3),
        ]
        result = self._stop(events, cwd=_TEAMMATE_CWD, dirty=False)
        self.assertIsNotNone(result)


class TestTeammateWindowE2E(_HookTestCase):
    """AC4: drive a real gate end to end with a teammate-worktree cwd."""

    def test_teammate_idle_blocks_on_live_failure_after_lead_clear_anchor(self):
        events = [
            failing_tests_concern(agent_id="worktree-story-003"),
            session_anchor(),
            *filler(3),
        ]
        self._write_events(events)
        with patch("commits.get_uncommitted_files", return_value=[]):
            result = teammate_idle.run(
                _make_teammate_idle_input(cwd=_TEAMMATE_CWD), smm_dir=self.smm_dir
            )
        self.assertIsNotNone(result)


class TestKickoffOnlySessionE2E(_HookTestCase):
    """AC5, end to end: the session that produced the bug.

    Writer and reader are driven in sequence through the real hooks, against a
    real event log — no signal is hand-planted. `/xp-plan` ran a compound
    `plan_cli … && pytest …` that short-circuited at the VALIDATOR (design_details
    517/500 over budget) and exited 1. No test ran; no production code was
    written; the tree was clean and the suite green. 87 seconds later the Stop
    gate said "Tests are failing."
    """

    def _kickoff_session(self, command: str, error: str) -> str | None:
        self._write_events([session_anchor(), *filler(2)])
        bash_failure.run(
            _make_bash_failure_input(command=command, error=error, exit_code=1),
            smm_dir=self.smm_dir,
        )
        self.events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        with patch("commits.get_uncommitted_files", return_value=[]):
            return tdd_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

    def _observed_failure(self) -> dict:
        """The writer's record of the failed command — asserted POSITIVELY.

        Without this, every other assertion here is vacuous: `bash_failure.run`
        has five early returns (xp-agent, interrupt, no runner named, no SMM,
        bad agent id), and on ANY of them it writes nothing, the gate finds no
        signal, and a silent gate looks identical to a correctly-quiet one.
        This pins that the writer actually OBSERVED the failure and classified
        it — so the quiet gate below is quiet for the right reason.
        """
        failures = [
            e
            for e in events_of_type(self.events, EVENT_TYPE_STATUS)
            if e.get("metadata", {}).get("action") == STATUS_ACTION_BASH_FAILED
        ]
        self.assertEqual(len(failures), 1, "writer never recorded the failure")
        return failures[0]

    def test_kickoff_only_session_does_not_report_failing_tests(self):
        """AC1 + AC5. Falsifiable: make `attribute_failure` return the framework
        unconditionally (its behavior before this story) and this goes red.
        """
        result = self._kickoff_session(
            "python3 plan_cli.py validate --plan execution_plan.json "
            "&& python3 -m pytest plugins/xp-agents/tests",
            "Exit code 1\nValidation errors:\n  - design_details 517/500 OVER budget",
        )
        self.assertIsNone(result)

        # And the log tells the truth about what happened: the command failed,
        # but nothing claims a test failed.
        self.assertNotRegex(self._observed_failure()["content"], TEST_CONCERN_RE)
        self.assertEqual(events_of_type(self.events, EVENT_TYPE_CONCERN), [])

    def test_real_failing_run_in_the_same_session_still_blocks(self):
        """AC2, the control that makes the test above mean something. Same
        session shape, same hooks — but the runner actually ran and failed."""
        result = self._kickoff_session(
            "python3 -m pytest plugins/xp-agents/tests",
            "Exit code 1\n2 failed, 3 passed",
        )
        # The mirror of the test above: here the writer DID observe a run, so it
        # DOES make a test claim — and the gate acts on it.
        self.assertEqual(len(events_of_type(self.events, EVENT_TYPE_CONCERN)), 1)
        self.assertIsNotNone(result)
        self.assertIn("failing", str(result).lower())


if __name__ == "__main__":
    unittest.main()
