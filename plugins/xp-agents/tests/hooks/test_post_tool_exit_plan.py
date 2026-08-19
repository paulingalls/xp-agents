#!/usr/bin/env python3
"""Tests for PostToolUse:ExitPlanMode (post_tool_exit_plan.py).

Split from test_post_tool.py (story-026): this module's tests share no
fixture and no code path with `post_tool_use.py` or `bash_post_tool.py` —
extracted rather than left to push that file's own line count past the
450-line band, the placement CLAUDE.md's file-size rule calls for over
re-recording a higher ceiling.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import post_tool_exit_plan
from conftest import _HookTestCase

_WATERMARK_ID = "test-post-tool"


class TestPostToolExitPlan(_HookTestCase):
    """PostToolUse:ExitPlanMode writes marker, event, and returns context."""

    def test_returns_review_nudge(self):
        """Should return additionalContext nudging /xp-review-plan."""
        result = post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        result = self._assert_not_none(result)
        self.assertIn("xp-review-plan", result)

    def test_writes_marker_file(self):
        """Should create .plan-awaiting-review marker."""
        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertTrue(marker.exists())

    def test_writes_gate_event(self):
        """Should append plan_awaiting_review event tagged with plan_exited action."""
        from event_schema import STATUS_ACTION_PLAN_EXITED

        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)
        metadata = gate[0].get("metadata") or {}
        self.assertEqual(metadata.get("action"), STATUS_ACTION_PLAN_EXITED)

    def test_skips_xp_agents(self):
        """XP agent types should be skipped."""
        result = post_tool_exit_plan.run(
            {
                "session_id": "t",
                "agent_id": "main",
                "agent_type": "xp-test",
                "tool_name": "ExitPlanMode",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertFalse(marker.exists())

    def test_no_smm_dir_returns_none(self):
        """Missing SMM dir should return None gracefully."""
        result = post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=Path("/nonexistent/path"),
        )
        self.assertIsNone(result)

    def test_marker_contains_plan_path_from_tool_response(self):
        """Marker should contain the filePath from ExitPlanMode tool_response."""
        import markers

        plan_path = "/home/user/.claude/plans/my-plan.md"
        post_tool_exit_plan.run(
            {
                "session_id": "t",
                "agent_id": "main",
                "tool_name": "ExitPlanMode",
                "tool_response": {"filePath": plan_path},
            },
            smm_dir=self.smm_dir,
        )
        content = markers.marker_read(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self.assertEqual(content, plan_path)

    def test_marker_falls_back_to_agent_id_without_tool_response(self):
        """Without tool_response, marker should contain agent_id as fallback."""
        import markers

        post_tool_exit_plan.run(
            {"session_id": "t", "agent_id": "main", "tool_name": "ExitPlanMode"},
            smm_dir=self.smm_dir,
        )
        content = markers.marker_read(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self.assertEqual(content, "main")


if __name__ == "__main__":
    import unittest

    unittest.main()
