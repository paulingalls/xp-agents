#!/usr/bin/env python3
"""Tests for pre_tool_write.py: plan review gate, assign gate, question gate,
accept marker.

Split from test_pre_tool_write.py -- keeps gate-related test classes separate.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import pre_tool_write
import sprint_state
from conftest import (
    SPRINT_CLOSING_ONLY,
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    SPRINT_REVIEWING_ONLY,
    _HookTestCase,
    _make_write_input,
)


class TestPreToolWritePlanReviewGate(_HookTestCase):
    """PreToolUse blocks writes when plan is unreviewed."""

    def test_unreviewed_plan_blocks_write(self):
        """Write with .plan-awaiting-review marker should block."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-review-plan", str(ctx.exception))

    def test_plan_file_write_allowed_with_marker(self):
        """Write to .claude/plans/ should be allowed even with marker."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan\n1. Do stuff",
            },
        )
        result = pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        # Should NOT raise -- plan files are exempt
        if result:
            self.assertNotIn("xp-review-plan", result)

    def test_no_marker_no_block(self):
        """Write without marker should not block."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        # Should not raise -- result is None or context string
        if result:
            self.assertNotIn("xp-review-plan", result)

    def test_marker_removed_no_block(self):
        """Write after marker removed should not block."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.touch()
        marker.unlink()
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-review-plan", result)


class TestAssignPendingGate(_HookTestCase):
    """PreToolUse blocks writes when /xp-assign hasn't run."""

    def test_assign_pending_blocks_write(self):
        """Write with .assign-pending marker should block."""
        marker = self.smm_dir / ".assign-pending"
        marker.touch()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-assign", str(ctx.exception))

    def test_plan_file_exempt_from_assign_gate(self):
        """Write to .claude/plans/ allowed with assign-pending marker."""
        marker = self.smm_dir / ".assign-pending"
        marker.touch()
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan\n1. Do stuff",
            },
        )
        result = pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-assign", result)

    def test_no_assign_marker_no_block(self):
        """Write without assign-pending marker should not block."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-assign", result)


class TestQuestionGate(_HookTestCase):
    """PreToolUse blocks writes when a blocking question is unanswered."""

    def test_question_gate_blocks_write(self):
        """Write with .question-gate should block."""
        gate = self.smm_dir / ".question-gate"
        gate.write_text("test-question-id")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("AskUserQuestion", str(ctx.exception))

    def test_no_question_gate_no_block(self):
        """Write without .question-gate should not block."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("AskUserQuestion", result)


class TestAcceptMarker(_HookTestCase):
    """pre_tool_write sets accept marker when in-progress stories exist."""

    def test_sets_accept_marker_when_in_progress_stories(self):
        """Write + in-progress stories -> marker set."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_no_marker_when_no_sprint(self):
        """Write + no sprint -> no marker."""
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_marker_when_no_in_progress(self):
        """Write + all ready stories -> no marker."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_marker_when_only_reviewing_stories(self):
        # Regression guard for the .accept marker re-arm carve-out: a
        # story in 'reviewing' status is mid-acceptance; xp-accept (and
        # its child xp-story-close) legitimately Edit during fix-cycles.
        # Pre_tool_write must NOT re-arm the .accept marker on those
        # Edits — otherwise the subsequent update-story done call is
        # blocked. The fix relies on has_in_progress_stories exact-
        # matching "in-progress" only; this test pins that exact-match
        # contract going forward.
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_idempotent_marker_setting(self):
        """Marker already exists -> no error, still exists."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_plan_file_does_not_set_marker(self):
        """Plan file writes should not trigger accept marker."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan",
            },
        )
        pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_rearm_when_reviewing_story_present(self):
        # Story-004: ACCEPT_ACTIVE marker removed; close-then-done makes
        # has_reviewing_stories the structural "we're inside the accept
        # window" signal. pre_tool_write must NOT re-arm .accept on
        # Edits when ANY story is in `reviewing` — even if other
        # stories remain in-progress (which keeps has_in_progress True).
        # Pins the contract that unblocks incremental teammate accept.
        # Sprint with 2 stories: one in-progress, one reviewing.
        from conftest import _s, _sprint_json

        sprint_json = _sprint_json(
            [
                _s("story-001", "a", "in-progress"),
                _s("story-002", "b", "reviewing"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(sprint_json)
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        self.assertTrue(sprint_state.has_reviewing_stories(self.smm_dir))
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

    def test_no_marker_when_only_closing_stories(self):
        # Story-005: extends the reviewing-suppression carve-out to the new
        # `closing` state. A story in `closing` is mid-/xp-story-close
        # (review → push → merge); fix-cycle Edits during that window must
        # NOT re-arm .accept, otherwise the subsequent update-story done
        # call is blocked. Mirrors test_no_marker_when_only_reviewing_stories.
        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_ONLY)
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_no_rearm_when_closing_story_present(self):
        # Story-005: mixed in-progress + closing — the close-window suppression
        # must fire even when siblings remain in-progress. Mirrors
        # test_no_rearm_when_reviewing_story_present for the closing state.
        from conftest import _s, _sprint_json

        sprint_json = _sprint_json(
            [
                _s("story-001", "a", "in-progress"),
                _s("story-002", "b", "closing"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(sprint_json)
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        self.assertTrue(sprint_state.has_closing_stories(self.smm_dir))
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

    def test_rearm_when_in_progress_only_no_reviewing(self):
        # Inverse pin: with in-progress stories AND no reviewing, the
        # re-arm fires. close-then-done window not active.
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        self.assertFalse(sprint_state.has_reviewing_stories(self.smm_dir))
        pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT))


if __name__ == "__main__":
    unittest.main()
