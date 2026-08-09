#!/usr/bin/env python3
"""The sprint-review gate against a reviewer that is already running.

Split from test_sprint_stop_gate.py, which sits at its recorded size ceiling —
and which matches the convention anyway: one file per feature under test.

The gate's review step clears on a sprint_end event. The reviewer is an
Agent-tool subagent and the harness backgrounds those, so at Stop time no
sprint_end exists yet and the gate told the agent to run the review it was
already inside. Suppressing on a bounded in-flight record is what tells
"not started" from "in flight"; the wording is untouched, because an
instruction the agent cannot verify stops being a gate.

Timestamps here are seeded against the real clock, not a frozen one: the gate
takes no clock parameter, so these read the same clock the writer stamps.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import sprint_review_flight
import sprint_stop_gate
import subagent_start
import subagent_stop
from conftest import (
    SPRINT_COMPLETE_WITH_ID,
    SPRINT_REVIEWING_ONLY,
    _HookTestCase,
    _make_stop_input,
)

_SESSION = "session-under-test"
_OTHER_SESSION = "some-other-session"

_STALE_AGO = sprint_review_flight.STALE_AFTER_SECONDS + 1


class _ReviewGateTestCase(_HookTestCase):
    """A complete sprint with no sprint_end event — the gate's firing state."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)

    def gate(self, session_id: str = _SESSION, **overrides):
        payload = _make_stop_input(session_id=session_id, **overrides)
        return sprint_stop_gate.run(payload, smm_dir=self.smm_dir)

    def arm(self, session_id: str = _SESSION, ago: float = 0.0) -> None:
        markers.marker_write(
            self.smm_dir,
            sprint_review_flight.marker(session_id),
            {"session_id": session_id, "started_at": time.time() - ago},
        )

    def start_reviewer(self, agent_type: str = "xp-sprint-reviewer") -> None:
        subagent_start.run(
            {
                "session_id": _SESSION,
                "agent_id": "reviewer-1",
                "agent_type": agent_type,
                "hook_event_name": "SubagentStart",
                "cwd": str(self.smm_dir),
            },
            smm_dir=self.smm_dir,
        )

    def stop_reviewer(self, agent_type: str = "xp-sprint-reviewer") -> None:
        subagent_stop.run(
            {
                "session_id": _SESSION,
                "agent_id": "reviewer-1",
                "agent_type": agent_type,
                "last_assistant_message": "Review complete.",
            },
            smm_dir=self.smm_dir,
        )


class TestNotStarted(_ReviewGateTestCase):
    """No record: the gate must say exactly what it says today.

    Byte for byte against the constant, not a substring. The fix must not
    weaken the gate where it is already correct — softening the wording was
    considered and rejected, because an instruction the agent cannot verify
    stops being a gate.
    """

    def test_blocks_with_todays_message_verbatim(self):
        self.assertEqual(self.gate(), sprint_stop_gate._REVIEW_MESSAGE)


class TestInFlight(_ReviewGateTestCase):
    """A record for THIS session, inside the window: the reviewer is running."""

    def test_a_fresh_record_suppresses_the_gate(self):
        self.arm()
        self.assertIsNone(self.gate())

    def test_a_stale_record_still_blocks(self):
        # Two states, not three: a reviewer that armed the record and died
        # leaves the same honest instruction as one that never started — run
        # the review. Same message, so no new wording is introduced.
        self.arm(ago=_STALE_AGO)
        self.assertEqual(self.gate(), sprint_stop_gate._REVIEW_MESSAGE)

    def test_another_sessions_record_does_not_suppress(self):
        # The SMM is shared across worktrees and windows. A neighbour's review
        # is not evidence that this session's has run.
        self.arm(session_id=_OTHER_SESSION)
        self.assertEqual(self.gate(), sprint_stop_gate._REVIEW_MESSAGE)

    def test_freshness_is_read_before_the_event_log(self):
        # The reviewer is concurrently appending to events.jsonl, and a fresh
        # record answers regardless of what is in there — so the check comes
        # first and no Stop during the review takes the log lock.
        self.arm()
        with mock.patch.object(
            sprint_stop_gate._common, "read_events_locked"
        ) as read_events:
            self.assertIsNone(self.gate())
        read_events.assert_not_called()


class TestAcceptBranchIsUntouched(_ReviewGateTestCase):
    """The record suppresses the REVIEW step only.

    The accept step fires on a different state for a different reason, and a
    running sprint reviewer says nothing about whether stories were accepted.
    """

    def test_a_fresh_record_does_not_suppress_the_accept_gate(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        self.arm()
        result = self.gate()
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)


class TestRealSubagentRoundTrip(_ReviewGateTestCase):
    """Drive the WRITE half for real, then read it with the gate.

    Hand-writing the record and exercising only the gate passes identically
    against a `subagent_start.py` that writes nothing — that tests
    reachability, not behaviour.
    """

    def test_gate_passes_after_a_real_subagent_start(self):
        self.start_reviewer()
        self.assertIsNone(self.gate())

    def test_qualified_agent_type_also_records(self):
        self.start_reviewer(agent_type="xp-agents:xp-sprint-reviewer")
        self.assertIsNone(self.gate())

    def test_a_different_agent_type_records_nothing(self):
        self.start_reviewer(agent_type="xp-code-reviewer")
        self.assertEqual(self.gate(), sprint_stop_gate._REVIEW_MESSAGE)

    def test_the_reviewers_exit_retires_the_record(self):
        # Otherwise the record would outlive the run and go on suppressing a
        # gate whose sprint_end never landed.
        self.start_reviewer()
        self.stop_reviewer()
        self.assertFalse(
            markers.marker_path(
                self.smm_dir, sprint_review_flight.marker(_SESSION)
            ).exists()
        )

    def test_a_qualified_exit_retires_the_record_too(self):
        self.start_reviewer()
        self.stop_reviewer(agent_type="xp-agents:xp-sprint-reviewer")
        self.assertFalse(
            markers.marker_path(
                self.smm_dir, sprint_review_flight.marker(_SESSION)
            ).exists()
        )

    def test_the_gate_is_satisfied_after_a_completed_review(self):
        # End to end: start suppresses, and the sprint_end the reviewer's exit
        # emits is what clears the gate for good — the record is only the
        # bridge across the window where no sprint_end exists yet.
        self.start_reviewer()
        self.stop_reviewer()
        self.assertIsNone(self.gate())


class TestInjectionTierUnchanged(_ReviewGateTestCase):
    """Arming the record must not change what the reviewer is handed.

    `xp-sprint-reviewer` used to fall through to the xp-* fallback: no SMM
    payload, sequential note kept. Naming it in the tier registry is what lets
    the record be armed, and it is also the one way to silently give or take
    away context the agent was tuned for. So compare against another agent
    type still served by that fallback, byte for byte.
    """

    def injection(self, agent_type: str) -> str | None:
        return subagent_start.run(
            {
                "session_id": _SESSION,
                "agent_id": "agent-1",
                "agent_type": agent_type,
            },
            smm_dir=self.smm_dir,
        )

    def test_injection_matches_the_fallback_it_replaced(self):
        self.assertEqual(
            self.injection("xp-sprint-reviewer"),
            self.injection("xp-close-reviewer"),
        )

    def test_the_sequential_note_is_kept(self):
        result = self.injection("xp-sprint-reviewer")
        result = self._assert_not_none(result)
        self.assertIn(subagent_start.SEQUENTIAL_DISCIPLINE_NOTE, result)


class TestExistingEarlyReturnsSurvive(_ReviewGateTestCase):
    """Regressions the gate already had, checked against the new short-circuit."""

    def test_xp_agent_defers(self):
        self.assertIsNone(self.gate(agent_type="xp-code-reviewer"))

    def test_stop_hook_active_defers(self):
        self.assertIsNone(self.gate(stop_hook_active=True))

    def test_missing_smm_defers(self):
        self.assertIsNone(
            sprint_stop_gate.run(_make_stop_input(), smm_dir=Path("/nonexistent-smm"))
        )


if __name__ == "__main__":
    unittest.main()
