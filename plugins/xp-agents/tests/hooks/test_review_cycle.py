#!/usr/bin/env python3
"""Tests for review cycle hooks: review_cycle_done and subagent review flags.

Split from test_subagent.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import review_cycle_done
import security
import subagent_stop
from conftest import _HookTestCase, _make_agent_input, _make_skill_input


class TestReviewCycleDone(_HookTestCase):
    """PostToolUse:Skill|Agent hook sets flags after review skills or xp-housekeeper."""

    def test_security_review_sets_flag_and_marker(self):
        review_cycle_done.run(
            _make_skill_input("security-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["security_review_done"])
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_simplify_sets_flag(self):
        review_cycle_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        # Simplify should NOT write security marker
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_quality_review_sets_flag(self):
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_security_triage_sets_flag(self):
        review_cycle_done.run(
            _make_skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["security_review_done"])
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def _action_events(self, action: str) -> list[dict]:
        events = _common.read_events_raw(self.smm_dir)
        return [e for e in events if e.get("metadata", {}).get("action") == action]

    def test_simplify_emits_action_event(self):
        """/simplify completion appends a status event with action=simplify_complete."""
        review_cycle_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        emitted = self._action_events("simplify_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "status")

    def test_quality_review_emits_action_event(self):
        """/xp-quality-review completion appends action=qr_complete."""
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        emitted = self._action_events("qr_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "status")

    def test_security_review_emits_action_event(self):
        """/security-review records exactly one event with action=security_complete."""
        review_cycle_done.run(
            _make_skill_input("security-review"), smm_dir=self.smm_dir
        )
        emitted = self._action_events("security_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "security-review")

    def test_security_triage_emits_complete_action(self):
        """Triage emits security_triage_complete and NEVER security_complete."""
        review_cycle_done.run(
            _make_skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        triage = self._action_events("security_triage_complete")
        review = self._action_events("security_complete")
        self.assertEqual(len(triage), 1, "expected one security_triage_complete")
        self.assertEqual(len(review), 0, "triage must not emit security_complete")

    def test_plan_review_emits_action_event(self):
        """/xp-review-plan completion appends action=plan_reviewed."""
        review_cycle_done.run(_make_skill_input("xp-review-plan"), smm_dir=self.smm_dir)
        emitted = self._action_events("plan_reviewed")
        self.assertEqual(len(emitted), 1)

    def test_housekeeping_emits_action_event(self):
        """xp-housekeeper agent completion appends action=housekeeping_complete."""
        review_cycle_done.run(_make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir)
        emitted = self._action_events("housekeeping_complete")
        self.assertEqual(len(emitted), 1)

    def test_qualified_simplify_name(self):
        """Plugin-qualified skill names also match."""
        review_cycle_done.run(
            _make_skill_input("xp-agents:simplify"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_ignores_other_skills(self):
        review_cycle_done.run(_make_skill_input("xp-kickoff"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])
        self.assertFalse(cycle["security_review_done"])

    def test_xp_agent_skips(self):
        result = review_cycle_done.run(
            _make_skill_input(agent_type="xp-test"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_simplify_nudges_quality_review(self):
        """After /simplify, nudge to run /xp-quality-review."""
        result = review_cycle_done.run(
            _make_skill_input("simplify"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_quality_review_nudges_security_review(self):
        """After /xp-quality-review, nudge to run /security-review."""
        result = review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("/security-review", result)

    def test_security_triage_nudges_commit(self):
        """After /xp-security-triage, nudge to commit."""
        result = review_cycle_done.run(
            _make_skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("commit", result.lower())

    def test_plan_review_nudges_task_creation(self):
        """After /xp-review-plan, nudge to create tasks."""
        result = review_cycle_done.run(
            _make_skill_input("xp-review-plan"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("TaskCreate", result)

    def test_plan_review_does_not_set_review_flags(self):
        """Plan review is not part of the commit review cycle."""
        review_cycle_done.run(_make_skill_input("xp-review-plan"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])
        self.assertFalse(cycle["security_review_done"])

    def test_qualified_plan_review_name(self):
        """Plugin-qualified /xp-review-plan also triggers nudge."""
        result = review_cycle_done.run(
            _make_skill_input("xp-agents:xp-review-plan"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("TaskCreate", result)

    def test_housekeeper_agent_returns_process_guide(self):
        """After xp-housekeeper Agent call, inject PROCESS_GUIDE.md as context."""
        result = review_cycle_done.run(
            _make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("Practicing the Values", result)

    def test_housekeeper_qualified_name(self):
        """Plugin-qualified xp-agents:xp-housekeeper also triggers process guide."""
        result = review_cycle_done.run(
            _make_agent_input("xp-agents:xp-housekeeper"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("Practicing the Values", result)

    def test_housekeeper_does_not_set_review_flags(self):
        """Housekeeper is not part of the commit review cycle."""
        review_cycle_done.run(_make_agent_input("xp-housekeeper"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])
        self.assertFalse(cycle["security_review_done"])

    def test_worktree_cwd_scopes_markers(self):
        """Worktree cwd uses resolve_agent_id for marker scoping."""
        inp = _make_skill_input(
            "simplify",
            agent_id="",
            cwd="/proj/.claude/worktrees/teammate-story-001",
        )
        review_cycle_done.run(inp, smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "teammate-story-001")
        self.assertTrue(cycle["simplify_done"])
        main_cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(main_cycle.get("simplify_done", False))


class TestSubagentStopReviewFlags(_HookTestCase):
    """SubagentStop backup: detect review-related subagent completions."""

    def _stop_input(self, agent_id: str, agent_type: str = "", **overrides) -> dict:
        data = {
            "session_id": "t",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": "Done",
        }
        data.update(overrides)
        return data

    def test_simplify_agent_type_sets_flag(self):
        """SubagentStop with agent_type containing 'simplify' sets flag."""
        subagent_stop.run(
            self._stop_input("task-1", agent_type="simplify"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_quality_review_agent_type_sets_flag(self):
        """SubagentStop with agent_type 'xp-quality-review' sets flag."""
        subagent_stop.run(
            self._stop_input("task-2", agent_type="xp-quality-review"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_simplify_agent_id_sets_flag(self):
        """SubagentStop with agent_id containing 'simplify' sets flag."""
        subagent_stop.run(
            self._stop_input("simplify-reuse-1", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_regular_subagent_no_flag(self):
        """Regular subagent does not set any review flags."""
        subagent_stop.run(
            self._stop_input("task-3", agent_type="task"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_plan_subagent_no_review_flag(self):
        """Plan subagent writes plan marker but not review flags."""
        subagent_stop.run(
            self._stop_input("plan-1", agent_type="Plan"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])


class TestPlanReviewerSetsAssignPending(_HookTestCase):
    """SubagentStop for xp-plan-reviewer sets .assign-pending marker."""

    def _stop_input(self, agent_id: str, agent_type: str = "") -> dict:
        return {
            "session_id": "t",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": "Review complete",
        }

    def test_plan_reviewer_sets_assign_marker(self):
        """xp-plan-reviewer completion creates .assign-pending marker."""
        subagent_stop.run(
            self._stop_input("review-1", agent_type="xp-plan-reviewer"),
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".assign-pending"
        self.assertTrue(marker.exists(), "assign-pending marker not created")

    def test_plan_reviewer_returns_nudge(self):
        """xp-plan-reviewer completion returns additionalContext nudge."""
        result = subagent_stop.run(
            self._stop_input("review-1", agent_type="xp-plan-reviewer"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-assign", result)

    def test_non_reviewer_no_assign_marker(self):
        """Other xp-* agents don't set assign-pending marker."""
        subagent_stop.run(
            self._stop_input("retro-1", agent_type="xp-retrospective"),
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".assign-pending"
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
