#!/usr/bin/env python3
"""Tests for subagent_stop and user_prompt_log hooks.

SubagentStart tests moved to test_subagent_tiers.py.
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
    _s,
    _sprint_json,
    make_event,
    write_smm_fixture,
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
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "Hello world")

    def test_agent_id_is_customer(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_xp_agent_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi", "agent_type": "xp-housekeeping"},
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
        ci = [e for e in events if e.get("type") == "customer_input"]
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
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 15000
        user_prompt_log.run(
            {"session_id": "t", "prompt": long_prompt},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_goals_present_no_block(self):
        """With goals recorded, prompt proceeds normally."""
        self._write_events([make_event("goal", content="Ship MVP")])
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
            {"session_id": "t", "prompt": "hi", "agent_type": "xp-housekeeping"},
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
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("task-1", statuses[0]["content"])
        self.assertEqual(statuses[0]["working_on"], [])

    def test_xp_agent_skips(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-housekeeping",
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
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("subagent", statuses[0]["content"])

    def test_missing_last_message(self):
        subagent_stop.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_conflict_detection_runs(self):
        # Set up a contradiction in the log
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
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
        concerns = [e for e in events if e.get("type") == "concern"]
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
            [make_event("status", agent_id="main", working_on=["src/a.ts"])]
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
        concerns = [e for e in events if e.get("type") == "concern"]
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
        """Both completion status and gate marker should be written."""
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
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 2)  # completion + gate


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


_SPRINT_REVIEW_MIXED = _sprint_json(
    [
        _s("story-001", "Login", "done"),
        _s("story-002", "Register", "done"),
        _s("story-003", "Logout", "deferred"),
        _s("story-004", "Profile", "ready"),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)


class TestSprintReviewerDone(_HookTestCase):
    """subagent_stop._handle_sprint_review_done runs after xp-sprint-reviewer."""

    def _reviewer_input(self, agent_type: str = "xp-sprint-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Review complete.",
        }

    def _seed_sprint(self, content: str = _SPRINT_REVIEW_MIXED) -> None:
        (self.smm_dir / "sprint.json").write_text(content)

    def test_returns_none_no_nudge(self):
        """M6: After sprint-reviewer finishes, returns None — sprint retro
        now runs at next session start, not end of session."""
        self._seed_sprint()
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_matches_qualified_agent_type(self):
        """Should match agent_type 'xp-agents:xp-sprint-reviewer' too —
        writes the sprint_end event even if return value is None."""
        self._seed_sprint()
        subagent_stop.run(
            self._reviewer_input(agent_type="xp-agents:xp-sprint-reviewer"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        self.assertEqual(len(sprint_events), 1)

    def test_logs_sprint_end_event(self):
        """Sprint end event has type=sprint, action=end, velocity metadata."""
        self._seed_sprint()
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        self.assertEqual(len(sprint_events), 1)
        meta = sprint_events[0].get("metadata", {})
        self.assertEqual(meta["action"], "end")
        self.assertEqual(meta["sprint_id"], "sprint-001")
        self.assertIn("stories_planned", meta)
        self.assertIn("stories_delivered", meta)
        self.assertIn("stories_carried", meta)

    def test_sprint_end_velocity_values(self):
        """Velocity in sprint end event matches sprint.json data."""
        self._seed_sprint()
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        meta = sprint_events[0]["metadata"]
        self.assertEqual(meta["stories_planned"], 4)
        self.assertEqual(meta["stories_delivered"], 2)
        self.assertEqual(meta["stories_carried"], 1)

    def test_cleans_up_input_file(self):
        """Removes .sprint-review-input.json after handling."""
        self._seed_sprint()
        (self.smm_dir / ".sprint-review-input.json").write_text("{}")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".sprint-review-input.json").exists())

    def test_no_sprint_graceful(self):
        """M6: No sprint.json → still returns None (no nudge), no crash."""
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
