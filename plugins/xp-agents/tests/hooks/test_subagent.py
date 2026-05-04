#!/usr/bin/env python3
"""Tests for subagent_stop and user_prompt_log hooks.

SubagentStart tests moved to test_subagent_tiers.py.
Sprint reviewer tests moved to test_subagent_sprint_reviewer.py.
Review cycle tests in test_review_cycle.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import subagent_stop
import user_prompt_log
from conftest import (
    _HookTestCase,
    make_event,
    write_smm_fixture,
)
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_HOUSEKEEPING_COMPLETE,
    STATUS_ACTION_PLAN_AWAITING_REVIEW,
    STATUS_ACTION_PLAN_COMPLETED,
    STATUS_ACTION_PLAN_REVIEWED,
    STATUS_ACTION_SUBAGENT_COMPLETE,
    event_action,
)

# ===========================================================================
# user_prompt_log.py tests — Milestone 3.4
# ===========================================================================


class TestUserPromptLog(_HookTestCase):
    def test_logs_prompt_as_customer_input(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hello world"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == EVENT_TYPE_CUSTOMER_INPUT]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "Hello world")

    def test_agent_id_is_customer(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == EVENT_TYPE_CUSTOMER_INPUT]
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_xp_agent_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi", "agent_type": "xp-housekeeper"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=fake_dir,
        )

    def test_empty_prompt_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": ""},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == EVENT_TYPE_CUSTOMER_INPUT]
        self.assertEqual(len(ci), 0)

    def test_task_notification_skips(self):
        user_prompt_log.run(
            {
                "session_id": "t",
                "prompt": "<task-notification>\n<task-id>abc123</task-id>\n",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == EVENT_TYPE_CUSTOMER_INPUT]
        self.assertEqual(len(ci), 0)

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 15000
        user_prompt_log.run(
            {"session_id": "t", "prompt": long_prompt},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == EVENT_TYPE_CUSTOMER_INPUT]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_goals_present_no_block(self):
        """With goals recorded, prompt proceeds normally."""
        self._write_events([make_event(EVENT_TYPE_GOAL, content="Ship MVP")])
        result = user_prompt_log.run(
            {"session_id": "t", "prompt": "do something"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_clears_asking_user_marker(self):
        """UserPromptSubmit clears .asking-user so Stop gate resumes normal blocking."""
        import markers

        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        user_prompt_log.run(
            {"session_id": "t", "prompt": "continue"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASKING_USER))

    def test_clears_asking_user_marker_on_empty_prompt(self):
        """Even empty/whitespace prompts clear the marker — user is still engaged."""
        import markers

        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        user_prompt_log.run(
            {"session_id": "t", "prompt": "   "},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASKING_USER))

    def test_xp_agent_prompt_does_not_clear_marker(self):
        """xp-agent prompts must not clear the main agent's dialogue marker."""
        import markers

        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        user_prompt_log.run(
            {"session_id": "t", "prompt": "hi", "agent_type": "xp-housekeeper"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ASKING_USER))


# ===========================================================================
# subagent_stop.py tests — Milestone 3.4
# ===========================================================================


class TestSubagentStop(_HookTestCase):
    def test_records_minimal_status(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "general-purpose",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 1)
        self.assertIn("task-1", statuses[0]["content"])
        self.assertEqual(statuses[0]["working_on"], [])
        self.assertEqual(event_action(statuses[0]), STATUS_ACTION_SUBAGENT_COMPLETE)
        self.assertEqual(
            statuses[0].get("metadata", {}).get("agent_type"), "general-purpose"
        )

    def test_xp_agent_skips(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-retrospective",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=fake_dir,
        )

    def test_default_agent_id(self):
        subagent_stop.run(
            {"session_id": "t", "last_assistant_message": "Done"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 1)
        self.assertIn("subagent", statuses[0]["content"])

    def test_missing_last_message(self):
        subagent_stop.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 1)

    def test_conflict_detection_runs(self):
        # Set up a contradiction in the log
        a = make_event(EVENT_TYPE_ASSUMPTION, content="API is REST")
        d = make_event(
            EVENT_TYPE_DISCOVERY, content="Actually GraphQL", references=[a["id"]]
        )
        self._write_events([a, d])

        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_clears_coordination_entry(self):
        """SubagentStop should remove the agent's .coordination.json entry."""
        import coordination

        coordination.update_coordination(self.smm_dir, "task-1", ["src/app.py"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIn("task-1", data)

        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        data = coordination.read_coordination(self.smm_dir)
        self.assertNotIn("task-1", data)

    def test_clears_agent_scoped_markers(self):
        """SubagentStop should remove TDD tracker and review cycle markers."""
        import markers

        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, "task-1")
        markers.marker_write(
            self.smm_dir, markers.REVIEW_CYCLE, {"last_review_commit": ""}, "task-1"
        )

        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "task-1")
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.REVIEW_CYCLE, "task-1")
        )

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [make_event(EVENT_TYPE_STATUS, agent_id="main", working_on=["src/a.ts"])]
        )
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertEqual(len(concerns), 0)


class TestSubagentStopPlanGate(_HookTestCase):
    """SubagentStop writes plan gate for Plan subagents (Agent tool flow)."""

    def test_plan_writes_awaiting_review_marker(self):
        """Plan subagent should write marker file and gate event."""
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Write tests\n2. Implement",
            },
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertTrue(marker.exists())
        events = _common.read_events_raw(self.smm_dir)
        gate_events = [
            e for e in events if "plan_awaiting_review" in e.get("content", "")
        ]
        self.assertEqual(len(gate_events), 1)

    def test_plan_records_completion_and_gate(self):
        """Plan completion and gate events each carry their action discriminator."""
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Do stuff",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 2)
        actions = {event_action(e) for e in statuses}
        self.assertEqual(
            actions, {STATUS_ACTION_PLAN_COMPLETED, STATUS_ACTION_PLAN_AWAITING_REVIEW}
        )


class TestSubagentStopNoReviewerNudge(_HookTestCase):
    """subagent_stop.py no longer nudges xp-subagent-reviewer (removed)."""

    def test_regular_subagent_returns_none(self):
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_non_special_agent_returns_none(self):
        """xp-* agents without special handlers return None."""
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-retrospective",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


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
        events = _common.read_events_raw(self.smm_dir)
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
        events = _common.read_events_raw(self.smm_dir)
        kickoff_events = [e for e in events if e.get("agent_id") == "xp-kickoff-done"]
        self.assertEqual(len(kickoff_events), 1)
        self.assertEqual(
            event_action(kickoff_events[0]), STATUS_ACTION_HOUSEKEEPING_COMPLETE
        )

    def test_emits_subagent_complete_after_housekeeping(self):
        """A generic subagent_complete event is appended for housekeeper."""
        subagent_stop.run(self._housekeeping_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 2)
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1)
        self.assertEqual(sc[0].get("metadata", {}).get("agent_type"), "xp-housekeeper")


class TestPlanReviewerDone(_HookTestCase):
    """subagent_stop._handle_plan_review_done runs after xp-plan-reviewer."""

    def _reviewer_input(self, agent_type: str = "xp-plan-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "plan-reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Plan reviewed.",
        }

    def test_emits_plan_reviewed_action(self):
        """assign_pending event carries the plan_reviewed action."""
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        gate_events = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and "assign_pending" in e.get("content", "")
        ]
        self.assertEqual(len(gate_events), 1)
        self.assertEqual(event_action(gate_events[0]), STATUS_ACTION_PLAN_REVIEWED)

    def test_emits_subagent_complete_after_plan_review(self):
        """A generic subagent_complete event accompanies the assign_pending event."""
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertEqual(len(statuses), 2)
        sc = [e for e in statuses if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE]
        self.assertEqual(len(sc), 1)
        self.assertEqual(
            sc[0].get("metadata", {}).get("agent_type"), "xp-plan-reviewer"
        )


if __name__ == "__main__":
    unittest.main()
