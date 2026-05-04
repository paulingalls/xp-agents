#!/usr/bin/env python3
"""Tests for sprint_stop_gate.py — unified sprint lifecycle Stop gate.

Replaces TestAcceptGate. Covers the full cascade:
  1. in-progress + ACCEPT marker → block "run /xp-accept"
  2. sprint complete, no sprint_end event → block "run /xp-sprint-review"
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_COMPLETE_WITH_ID,
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    SPRINT_SCHEDULED_ONLY,
    _HookTestCase,
    _make_stop_input,
    make_event,
)
from event_schema import EVENT_TYPE_SPRINT


class TestSprintStopGateEarlyExits(_HookTestCase):
    """Common early exits and deferrals."""

    def test_xp_agent_skips(self):
        import sprint_stop_gate

        result = sprint_stop_gate.run(
            _make_stop_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        import sprint_stop_gate

        result = sprint_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_no_smm_dir_allows_stop(self):
        import sprint_stop_gate

        fake_dir = Path("/nonexistent/smm")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=fake_dir)
        self.assertIsNone(result)

    def test_no_sprint_file_allows_stop(self):
        import sprint_stop_gate

        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_review_cycle_active_allows_stop(self):
        """Defer when review cycle is in progress."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        markers.write_review_cycle(
            self.smm_dir,
            "main",
            {
                "simplify_done": True,
                "quality_review_done": False,
                "last_review_commit": "abc123",
            },
        )
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_teammates_active_allows_stop(self):
        """Defer when teammates are running."""
        import coordination
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        coordination.update_coordination(self.smm_dir, "worker-1", [])
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_live_teammate_worktree_allows_stop(self):
        """Defer when a teammate worktree exists (pre-first-write window)."""
        from unittest.mock import patch

        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")

        with patch("worktree.has_live_teammates", return_value=True):
            result = sprint_stop_gate.run(
                _make_stop_input(cwd="/fake/repo"),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_completed_review_cycle_does_not_defer(self):
        """All review flags True means cycle is done — don't defer, block."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        markers.write_review_cycle(
            self.smm_dir,
            "main",
            {
                "simplify_done": True,
                "quality_review_done": True,
                "last_review_commit": "abc123",
            },
        )
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        # All reviews done — cycle complete, should NOT defer
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("xp-accept", result)

    def test_asking_user_marker_allows_stop(self):
        """Defer when the main agent is mid-AskUserQuestion dialogue."""
        import markers
        import sprint_stop_gate

        # Sprint-review blocking condition: sprint complete, no sprint_end event
        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        # Sanity check: without the marker, this would block with _REVIEW_MESSAGE
        baseline = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(baseline)
        # With the marker set, the gate defers
        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


class TestSprintStopGateAcceptCascade(_HookTestCase):
    """Cascade step 1: accept gating."""

    def test_in_progress_with_accept_marker_blocks(self):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("xp-accept", result)

    def test_in_progress_without_accept_marker_allows_stop(self):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_orphan_accept_marker_allows_stop(self):
        """Marker with no in-progress stories — falls through to next cascade step."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        # No in-progress stories; ready stories means sprint not complete
        self.assertIsNone(result)

    def test_scheduled_only_does_not_block_stop(self):
        """Scheduled stories with no in-progress should NOT trigger the
        accept-cascade gate. Pinning the four-state lifecycle invariant:
        `scheduled` is queued, not actively worked, so /xp-accept doesn't
        apply. Without this distinction the Stop hook would fire after
        every story closed (the symptom that motivated the lifecycle work)."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        # Scheduled is non-terminal but the gate must only fire on
        # in-progress (active branches with possible commits).
        self.assertIsNone(result)


class TestSprintStopGateReviewCascade(_HookTestCase):
    """Cascade step 2: sprint review gating."""

    def test_sprint_complete_no_end_event_blocks(self):
        """Complete sprint with no sprint_end event → nudge for review."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("xp-sprint-review", result)

    def test_sprint_complete_with_end_event_falls_through(self):
        """M6: Sprint with end event allows stop — cascade ends at review."""
        import _common
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        event = make_event(
            EVENT_TYPE_SPRINT,
            agent_id="xp-sprint-reviewer",
            content="Sprint end",
            metadata={"sprint_id": "sprint-001", "action": "end"},
        )
        _common.append_safe(self.smm_dir, event)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        # Cascade ends at sprint-review. Sprint retro runs at next session
        # start via retrospective.py, not as a Stop gate.
        self.assertIsNone(result)

    def test_sprint_complete_no_sprint_id_allows_stop(self):
        """Malformed sprint.json with no sprint_id — can't match events, allow stop."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_end_event_for_other_sprint_still_blocks(self):
        """sprint_end for a DIFFERENT sprint_id doesn't satisfy the current sprint."""
        import _common
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        event = make_event(
            EVENT_TYPE_SPRINT,
            agent_id="xp-sprint-reviewer",
            content="Sprint end",
            metadata={"sprint_id": "sprint-999", "action": "end"},
        )
        _common.append_safe(self.smm_dir, event)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("xp-sprint-review", result)


class TestSprintStopGatePostReview(_HookTestCase):
    """M6: after sprint-review writes sprint_end, cascade is done. No retro
    gating at Stop — sprint retro runs at next session start."""

    def _seed_sprint_end(self, sprint_id: str = "sprint-001"):
        import _common

        event = make_event(
            EVENT_TYPE_SPRINT,
            agent_id="xp-sprint-reviewer",
            content="Sprint end",
            metadata={"sprint_id": sprint_id, "action": "end"},
        )
        _common.append_safe(self.smm_dir, event)

    def test_end_event_no_retro_does_not_block(self):
        """M6: sprint_end without sprint_retro_done no longer blocks — the
        cascade ends at sprint-review. User can stop freely."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        self._seed_sprint_end()
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


class TestSprintStopGateWorktreeAgentId(_HookTestCase):
    """Worktree cwd uses resolve_agent_id for deferral checks."""

    def test_worktree_cwd_reads_correct_review_cycle(self):
        """Mid-review deferral uses worktree-derived agent_id."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        markers.write_review_cycle(
            self.smm_dir,
            "teammate-story-001",
            {
                "simplify_done": True,
                "quality_review_done": False,
                "last_review_commit": "abc123",
            },
        )
        inp = _make_stop_input(
            agent_id="",
            cwd="/proj/.claude/worktrees/teammate-story-001",
        )
        result = sprint_stop_gate.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
