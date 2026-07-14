#!/usr/bin/env python3
"""Tests for pre_tool_write.py: plan review gate, question gate, accept marker.

Split from test_pre_tool_write.py -- keeps gate-related test classes separate.
The assign gate and the shared _LEAD_GATES machinery live in test_lead_gates.py:
the assign gate grew a state-derived `active_when` predicate and its suite with
it, and this file was already over the 500-line cap. The schedule gate lives in
test_pre_tool_write_schedule_gate.py: it is its own mechanism, with its own
trigger window and its own exemption set, and keeping its cases here would push
this file back over the cap.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import pre_tool_write
import sprint_state
import worktree
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

    def test_teammate_worktree_exempt_from_plan_gate(self):
        """A teammate never plans, so the lead's plan marker must not gate it.

        The parallel pipeline exists so the lead can plan story N+1 while a
        teammate executes story N; a global gate forbids exactly that state.
        """
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text("/Users/x/.claude/plans/lead-plan.md")
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        result = pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-review-plan", result)

    def test_in_place_teammate_exempt_from_plan_gate(self):
        """The in-place teammate runs in the MAIN checkout, so cwd cannot
        discriminate it. Its live in-place marker must, or solo delegation is
        gated by the lead's own plan marker."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text("/Users/x/.claude/plans/lead-plan.md")
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-010")
        in_place_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/src",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with patch.dict(
            os.environ, {"XP_TEAMMATE_NAME": "worktree-story-010"}, clear=False
        ):
            result = pre_tool_write.run(in_place_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-review-plan", result)


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

    def test_question_gate_message_names_self_resolve_antipattern(self):
        """The gate message must say AskUserQuestion is the ONLY clear path and
        warn that a decision/status self-resolve does not clear it — the wording
        that keeps a literal-minded agent off the self-resolve anti-pattern."""
        (self.smm_dir / ".question-gate").write_text("test-question-id")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        msg = str(ctx.exception)
        self.assertIn("AskUserQuestion", msg)
        self.assertIn("only", msg.lower())
        # Names the anti-pattern: a decision/status event does not clear it.
        self.assertIn("decision", msg.lower())
        self.assertIn("fabricat", msg.lower())

    def test_teammate_worktree_exempt_from_question_gate(self):
        """A teammate cannot clear a question gate, so it must not be gated.

        The marker lives in the SHARED SMM dir and AskUserQuestion is the ONLY
        thing that clears it -- but a headless teammate has no user to ask. A
        gated teammate is stranded mid-implementation with no recovery path.
        """
        (self.smm_dir / ".question-gate").write_text("test-question-id")
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        result = pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("AskUserQuestion", result)

    def test_in_place_teammate_exempt_from_question_gate(self):
        """The in-place teammate shares the main checkout's cwd, so only its
        live in-place marker discriminates it. It is just as unable to answer."""
        (self.smm_dir / ".question-gate").write_text("test-question-id")
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-010")
        in_place_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/src",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with patch.dict(
            os.environ, {"XP_TEAMMATE_NAME": "worktree-story-010"}, clear=False
        ):
            result = pre_tool_write.run(in_place_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("AskUserQuestion", result)

    def test_lead_still_gated_while_a_teammate_is_live(self):
        """Positive control for the teammate exemption.

        A live in-place teammate marker sits in the SMM dir, but THIS process is
        the lead (no XP_TEAMMATE_NAME, cwd is the main checkout). The lead is the
        only agent that can call AskUserQuestion, so it must still be gated. Pins
        that the exemption keys on the writer's OWN identity -- not on the mere
        existence of some teammate marker somewhere in the shared dir.
        """
        (self.smm_dir / ".question-gate").write_text("test-question-id")
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-010")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/Users/dev/proj/src"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("AskUserQuestion", str(ctx.exception))

    def test_lead_with_leaked_env_and_matching_live_marker_is_exempt(self):
        """The one lead-facing behavior delta this branch ships, pinned.

        The gates now hand smm_dir to the probe; the old code let its env leg
        fall back to $SMM_DIR, which is normally unset for a lead, so the leg
        failed CLOSED to gated. A lead carrying a leaked XP_TEAMMATE_NAME AND a
        matching live in-place marker therefore flips from gated to exempt.

        This is the probe's documented intent -- the marker is what makes the
        leaky env var trustworthy, and only spawn_teammate writes it -- but it
        is a real delta, so it is pinned rather than left to prose. Note the
        sibling control above: a live marker for a name the writer does NOT
        carry leaves the lead gated. The name must MATCH.
        """
        (self.smm_dir / ".question-gate").write_text("test-question-id")
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-010")
        with patch.dict(
            os.environ, {"XP_TEAMMATE_NAME": "worktree-story-010"}, clear=False
        ):
            os.environ.pop("SMM_DIR", None)
            result = pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/Users/dev/proj/src"),
                smm_dir=self.smm_dir,
            )
        if result:
            self.assertNotIn("AskUserQuestion", result)

    def test_gate_persists_after_decision_metadata_resolves(self):
        """Regression guard: a decision with metadata.resolves=[question_id]
        must NOT clear the gate (only AskUserQuestion's answer event does).
        Characterizes already-correct behavior so a future change can't quietly
        let an event self-resolve the gate."""
        question_id = "test-question-id"
        gate = self.smm_dir / ".question-gate"
        gate.write_text(question_id)
        # The anti-pattern: agent records a decision resolving the question id.
        _common.append_safe(
            self.smm_dir,
            _common.make_event(
                "decision",
                "main",
                "Self-resolve attempt",
                topic="bogus",
                metadata={"resolves": [question_id]},
            ),
        )
        self.assertTrue(gate.exists(), "decision event must not consume the gate")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("AskUserQuestion", str(ctx.exception))


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
