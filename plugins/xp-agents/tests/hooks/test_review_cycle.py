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
import subagent_stop
from conftest import _HookTestCase, _make_agent_input, _make_skill_input
from event_schema import event_action


class TestReviewCycleDone(_HookTestCase):
    """PostToolUse:Skill|Agent hook sets flags after review skills or xp-housekeeper."""

    def test_simplify_sets_flag(self):
        review_cycle_done.run(_make_skill_input("simplify"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_quality_review_sets_flag(self):
        review_cycle_done.run(
            _make_skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def _action_events(self, action: str) -> list[dict]:
        events = _common.read_events_raw(self.smm_dir)
        return [e for e in events if event_action(e) == action]

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
        # agent_id is attribution (teammate-resolved); skill identity lives
        # in metadata.action. _make_skill_input defaults agent_id to "main".
        self.assertEqual(emitted[0]["agent_id"], "main")

    def test_security_review_returns_continuation_nudge(self):
        """/security-review completion returns continuation context so orchestrated
        callers (close-skill Step 4.5 gate) can proceed past the skill's
        'reply with markdown report only' stop-instruction.
        """
        result = review_cycle_done.run(
            _make_skill_input("security-review"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("orchestrated", result.lower())

    def test_security_review_for_xp_agent_emits_event_and_returns_nudge(self):
        """xp-* subagents invoking /security-review (e.g. xp-close-reviewer for
        Tier 3 close) MUST receive both the SECURITY_COMPLETE event and the
        continuation nudge — the recursion-prevention skip excludes
        /security-review because the close-reviewer is the primary intended
        caller.
        """
        input_data = _make_skill_input(
            "security-review", agent_type="xp-close-reviewer"
        )
        result = review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("orchestrated", result.lower())
        emitted = self._action_events("security_complete")
        self.assertEqual(len(emitted), 1)

    def test_xp_agent_skips_simplify(self):
        """The recursion-prevention skip remains in effect for /simplify
        invocations from xp-* subagents — only /security-review is excepted.
        """
        input_data = _make_skill_input("simplify", agent_type="xp-test")
        result = review_cycle_done.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        emitted = self._action_events("simplify_complete")
        self.assertEqual(len(emitted), 0)

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

    def test_simplify_nudges_quality_review(self):
        """After /simplify, nudge to run /xp-quality-review."""
        result = review_cycle_done.run(
            _make_skill_input("simplify"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_plan_review_does_not_nudge_task_creation(self):
        """/xp-review-plan returns no additionalContext — execution mode isn't
        decided yet at plan-review time, so the nudge fires at /xp-assign
        where mode is known. Asserting None (not just 'no TaskCreate text')
        catches future regressions that would re-introduce a different
        plan-review nudge."""
        result = review_cycle_done.run(
            _make_skill_input("xp-review-plan"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_plan_review_does_not_set_review_flags(self):
        """Plan review is not part of the commit review cycle."""
        review_cycle_done.run(_make_skill_input("xp-review-plan"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_assign_nudge_covers_taskcreate_solo_and_teammates(self):
        """Mode-aware nudge after /xp-assign: must mention TaskCreate AND
        address both solo (per-step tasks) and teammate (coordination:
        wait/accept/close per story) modes so the agent knows what to
        track regardless of which mode xp-assign chose."""
        result = review_cycle_done.run(
            _make_skill_input("xp-assign"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("TaskCreate", result)
        lower = result.lower()
        self.assertIn("solo", lower)
        self.assertIn("teammate", lower)
        self.assertIn("/xp-accept", result)

    def test_assign_emits_action_event(self):
        """/xp-assign completion appends action=assign_complete so consumers
        (retro_metrics, analyzers) can detect the lifecycle event without
        regex-matching content."""
        review_cycle_done.run(_make_skill_input("xp-assign"), smm_dir=self.smm_dir)
        emitted = self._action_events("assign_complete")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "status")

    def test_assign_does_not_set_review_flags(self):
        """Assign is not part of the commit review cycle."""
        review_cycle_done.run(_make_skill_input("xp-assign"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_qualified_assign_name(self):
        """Plugin-qualified xp-agents:xp-assign also triggers the nudge."""
        result = review_cycle_done.run(
            _make_skill_input("xp-agents:xp-assign"), smm_dir=self.smm_dir
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


class TestAgentIdSemantics(_HookTestCase):
    """agent_id is teammate attribution; metadata.action carries skill identity.

    review_cycle_done previously emitted lifecycle events with agent_id set
    to a skill-name string (e.g. "xp-quality-review"), drawn from a third
    tuple element in _TARGET_LIFECYCLE. Per the agent-id-semantics ADR
    (sprint-042), every hook producer writes the resolved teammate agent_id;
    skill identity lives in metadata.action.
    """

    def test_simplify_event_uses_resolved_agent_id(self):
        review_cycle_done.run(
            _make_skill_input("simplify", agent_id="teammate-7"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        emitted = [e for e in events if event_action(e) == "simplify_complete"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "teammate-7")

    def test_quality_review_event_uses_resolved_agent_id(self):
        review_cycle_done.run(
            _make_skill_input("xp-quality-review", agent_id="teammate-9"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        emitted = [e for e in events if event_action(e) == "qr_complete"]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["agent_id"], "teammate-9")


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
