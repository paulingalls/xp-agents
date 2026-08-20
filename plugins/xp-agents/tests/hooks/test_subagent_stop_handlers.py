#!/usr/bin/env python3
"""Tests for subagent_stop.py agent-type-specific completion handlers.

Split from test_subagent.py to stay under the 500-line cap. Covers
_handle_housekeeping_done (xp-housekeeper), _handle_plan_review_done
(xp-plan-reviewer), and _handle_close_reviewer_done (xp-close-reviewer).
Base subagent_stop/user_prompt_log behavior lives in test_subagent_core.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import assign_scope
import markers
import subagent_stop
from conftest import (
    _HookTestCase,
    write_smm_fixture,
)
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_STATUS,
    STATUS_ACTION_HOUSEKEEPING_COMPLETE,
    STATUS_ACTION_PLAN_REVIEWED,
    STATUS_ACTION_SUBAGENT_COMPLETE,
    event_action,
)

_WATERMARK_ID = "test-subagent"


class TestHousekeepingDone(_HookTestCase):
    """subagent_stop._handle_housekeeping_done runs after xp-housekeeper fork."""

    def _housekeeping_input(self, agent_type: str = "xp-housekeeper") -> dict:
        return {
            "session_id": "t",
            "agent_id": "housekeeper-1",
            "agent_type": agent_type,
            "last_assistant_message": "SMM curated.",
        }

    def test_returns_none(self):
        """Handler consumes markers and records event but returns None.

        SubagentStop does not support additionalContext — SMM is returned
        by the housekeeper agent itself, process guide injected via
        PostToolUse:Skill.
        """
        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        result = subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_matches_qualified_agent_type(self):
        """Should match agent_type 'xp-agents:xp-housekeeper' too."""
        result = subagent_stop.run(
            self._housekeeping_input(agent_type="xp-agents:xp-housekeeper"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_records_kickoff_done_event(self):
        """Should record a kickoff-done status event."""
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        done_events = [e for e in events if e.get("agent_id") == "xp-kickoff-done"]
        self.assertEqual(len(done_events), 1)
        self.assertIn("Kickoff complete", done_events[0]["content"])

    def test_graceful_without_smm_file(self):
        """No SMM file — still consumes markers and returns None."""
        (self.smm_dir / "shared_mental_model.json").unlink(missing_ok=True)
        result = subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_deletes_kickoff_marker(self):
        """Should delete .needs-kickoff marker after handling."""
        marker = self.smm_dir / ".needs-kickoff"
        marker.touch()
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        self.assertFalse(marker.exists())

    def test_clears_needs_housekeeping_marker(self):
        """Should clear .needs-housekeeping marker after handling."""
        (self.smm_dir / ".needs-housekeeping").write_text("kickoff")
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".needs-housekeeping").exists())

    def test_emits_housekeeping_complete_action(self):
        """Kickoff-done event carries the housekeeping_complete action."""
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        kickoff_events = [e for e in events if e.get("agent_id") == "xp-kickoff-done"]
        self.assertEqual(len(kickoff_events), 1)
        self.assertEqual(
            event_action(kickoff_events[0]), STATUS_ACTION_HOUSEKEEPING_COMPLETE
        )

    def test_emits_subagent_complete_after_housekeeping(self):
        """A generic subagent_complete event is appended for housekeeper."""
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 2)
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1)
        self.assertEqual(sc[0].get("metadata", {}).get("agent_type"), "xp-housekeeper")


class TestPlanReviewerDone(_HookTestCase):
    """subagent_stop._handle_plan_review_done runs after xp-plan-reviewer.

    The .assign-pending marker is now narrowed to teammate-mode plans: it is
    written only when the just-planned (in-progress) story is
    execution_mode=='teammate'. Solo/unset plan reviews leave no marker so the
    agent codes straight through without a spurious "run /xp-assign" block.
    """

    def _reviewer_input(self, agent_type: str = "xp-plan-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "plan-reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Plan reviewed.",
        }

    def _write_sprint(self, execution_mode=None, status="in-progress"):
        from conftest import _s, _sprint_json

        kw = {} if execution_mode is None else {"execution_mode": execution_mode}
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json([_s("story-001", "narrow gate", status, **kw)])
        )

    def _gate_events(self):
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and "assign_pending" in e.get("content", "")
        ]

    def test_emits_plan_reviewed_action(self):
        """Teammate-mode plan review: assign_pending event + plan_reviewed action.

        run() returns None — no continuing additionalContext. The nudge return
        was removed (debt 5e180220db1a): on SubagentStop it continued the
        reviewer's turn and buried its findings. The real gate is the marker +
        gate event below.
        """
        self._write_sprint(execution_mode="teammate")
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        gate_events = self._gate_events()
        self.assertEqual(len(gate_events), 1)
        self.assertEqual(event_action(gate_events[0]), STATUS_ACTION_PLAN_REVIEWED)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))

    def test_emits_subagent_complete_after_plan_review(self):
        """A generic subagent_complete event accompanies the assign_pending event."""
        self._write_sprint(execution_mode="teammate")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(len(statuses), 2)
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1)
        self.assertEqual(
            sc[0].get("metadata", {}).get("agent_type"), "xp-plan-reviewer"
        )

    def test_solo_leaves_no_marker_but_records_completion(self):
        """Solo-mode plan review: no marker, no assign_pending gate event,
        returns None — but the reviewer's subagent_complete AND a
        plan_reviewed completion record are both still recorded.

        plan_reviewed is a completion record, not a gate: /xp-review-plan
        converted from a forked skill (story-013), so this SubagentStop leg
        is now the sole producer for BOTH solo and teammate plans, same as
        quality_review_done never being gated on execution mode.
        """
        self._write_sprint(execution_mode="solo")
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))
        self.assertEqual(len(self._gate_events()), 0)
        statuses = events_of_type(
            _common.read_events_locked(self.smm_dir, _WATERMARK_ID), EVENT_TYPE_STATUS
        )
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1)
        pr = [e for e in statuses if event_action(e) == STATUS_ACTION_PLAN_REVIEWED]
        self.assertEqual(len(pr), 1)

    def test_unset_execution_mode_leaves_no_marker(self):
        """An in-progress story with no execution_mode is treated as non-teammate."""
        self._write_sprint(execution_mode=None)
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))

    def test_no_sprint_leaves_no_marker(self):
        """No sprint (free mode): graceful — no marker, returns None."""
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))

    def test_solo_review_does_not_block_next_write(self):
        """E2E (AC #3): after a solo plan review, the assign gate's marker is
        absent, so the agent's next write is not blocked."""
        import pre_tool_write

        self._write_sprint(execution_mode="solo")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))
        # The assign gate only blocks when .assign-pending exists; absent marker
        # means a Write proceeds. run() returns None (no block) here.
        write_input = {
            "session_id": "t",
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.smm_dir / "foo.py")},
            "cwd": "/tmp",
        }
        self.assertIsNone(pre_tool_write.run(write_input, smm_dir=self.smm_dir))


class TestPlanReviewerArmsScopedMarker(_HookTestCase):
    """The marker records WHICH stories it was armed for.

    Its payload used to be the reviewer's agent id, which no reader consumed.
    Scoping it is what lets the assign gate tell a marker armed for THIS plan
    review from one left over by an earlier, unrelated frontier — see
    tests/hooks/test_lead_gates_story_scope.py for the reading side.

    The format is spelled out here by hand, not built with the codec: this and
    the reader's copy are the two ends of the contract, and a codec-built
    expectation on both sides would let the format drift with both green.
    """

    def _reviewer_input(self) -> dict:
        return {
            "session_id": "t",
            "agent_id": "plan-reviewer-1",
            "agent_type": "xp-plan-reviewer",
            "last_assistant_message": "Plan reviewed.",
        }

    def _write_sprint(self, stories, sprint_id="sprint-042") -> None:
        from conftest import _sprint_json

        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(stories, sprint_id=sprint_id)
        )

    @staticmethod
    def _teammate(story_id: str, status: str = "in-progress") -> dict:
        from conftest import _s

        return _s(story_id, f"Story {story_id}", status, execution_mode="teammate")

    def test_payload_carries_the_sentinel_sprint_and_promoted_ids(self):
        """Only the PROMOTED teammate stories: a scheduled one has no teammate
        to spawn yet, and a solo one never will."""
        self._write_sprint(
            [
                self._teammate("story-001"),
                self._teammate("story-002"),
                self._teammate("story-003", status="scheduled"),
                {**self._teammate("story-004"), "execution_mode": "solo"},
            ]
        )
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertEqual(
            (self.smm_dir / ".assign-pending").read_text(),
            "sprint=sprint-042;stories=story-001,story-002",
        )

    def test_the_just_planned_story_is_always_in_scope(self):
        """The invariant that keeps the normal path from arming an empty scope:
        at plan-review-done the just-planned story is in-progress and delegated,
        so it is promoted by construction."""
        self._write_sprint([self._teammate("story-001")])
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertEqual(
            assign_scope.read_assign_scope(self.smm_dir, "sprint-042"),
            frozenset({"story-001"}),
        )

    def test_the_reader_rejects_the_payload_under_another_sprint(self):
        """Ties the recorded sprint id to its purpose: ids repeat every sprint
        and nothing sweeps this marker at a sprint boundary."""
        self._write_sprint([self._teammate("story-001")])
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(assign_scope.read_assign_scope(self.smm_dir, "sprint-043"))

    def test_an_id_that_cannot_round_trip_arms_no_scope_at_all(self):
        """The same "ids are unvalidated free strings" fact the sentinel exists
        for, applied to the ENCODER. An id carrying the list separator decodes
        as FRAGMENTS that match no story, which empties the intersection — and
        an empty intersection is the predicate's False, which DELETES a marker
        the lead still needs. Unencodable ids therefore drop the whole scope:
        the sentinel-less payload reads as legacy, and legacy stays armed.

        Asserted through the reader (the fail-closed answer is what matters),
        plus the marker still being ARMED — dropping the scope must not drop
        the gate.
        """
        self._write_sprint([self._teammate("story-001,story-002")])
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))
        self.assertIsNone(assign_scope.read_assign_scope(self.smm_dir, "sprint-042"))


class TestCloseReviewerDone(_HookTestCase):
    """subagent_stop._handle_close_reviewer_done consumes CLOSE_CYCLE_ACTIVE.

    Must run BEFORE the is_xp_agent skip — xp-close-reviewer is xp-* and
    would otherwise be silently skipped.
    """

    def _reviewer_input(self, agent_type: str = "xp-close-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "close-reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Close review complete.",
        }

    def test_close_reviewer_consumes_close_cycle_marker(self):
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".close-cycle-active").exists())

    def test_close_reviewer_marker_consume_idempotent_when_absent(self):
        # No marker present — must not crash
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".close-cycle-active").exists())

    def test_other_agent_does_not_consume_close_cycle_marker(self):
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        other_input = {
            "session_id": "t",
            "agent_id": "some-teammate",
            "agent_type": "some-teammate",
            "last_assistant_message": "ok",
        }
        subagent_stop.run(other_input, smm_dir=self.smm_dir)
        self.assertTrue((self.smm_dir / ".close-cycle-active").exists())

    def test_matches_qualified_agent_type(self):
        """Should match agent_type 'xp-agents:xp-close-reviewer' too."""
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        subagent_stop.run(
            self._reviewer_input(agent_type="xp-agents:xp-close-reviewer"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".close-cycle-active").exists())

    def test_close_reviewer_emits_subagent_complete_evidence(self):
        """Part 1: the handler emits the STANDARD subagent_complete event
        (agent_type=xp-close-reviewer) BEFORE consuming the marker — so the
        close-reviewer stops being the one subagent that leaves no completion
        trace. This is the evidence the gate cross-checks (story-002)."""
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)

        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = events_of_type(events, EVENT_TYPE_STATUS)
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1, "exactly one subagent_complete evidence event")
        self.assertEqual(
            sc[0].get("metadata", {}).get("agent_type"), "xp-close-reviewer"
        )
        # Marker still consumed — evidence emission does not replace teardown.
        self.assertFalse((self.smm_dir / ".close-cycle-active").exists())


if __name__ == "__main__":
    unittest.main()
