#!/usr/bin/env python3
"""Tests for sprint_stop_gate.py — unified sprint lifecycle Stop gate.

Replaces TestAcceptGate. Covers the full cascade:
  1. in-progress + ACCEPT marker → block "run /xp-accept"
  2. sprint complete, no sprint_end event → block "run /xp-sprint-review"
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_CLOSING_ONLY,
    SPRINT_COMPLETE_WITH_ID,
    SPRINT_IN_PROGRESS,
    SPRINT_REVIEWING_ONLY,
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
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_self_find_completed_review_does_not_defer(self):
        """Self-find per-increment review sets quality_review_done without
        simplify_done. That is a COMPLETED review, not mid-cycle — must NOT
        defer (the old `any and not all` heuristic wrongly deferred it)."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        markers.write_review_cycle(
            self.smm_dir,
            "main",
            {
                "simplify_done": False,
                "quality_review_done": True,
                "last_review_commit": "abc123",
            },
        )
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
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

    def test_accept_in_flight_marker_suppresses_reviewing(self):
        """Inside /xp-accept (marker armed), a reviewing story doesn't fire.

        The accept stop gate must not tell the agent to run the skill it is
        already inside — e.g. while awaiting background acceptance tests.
        """
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        # Baseline: without the marker, a reviewing story blocks "run /xp-accept"
        baseline = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        baseline = self._assert_not_none(baseline)
        self.assertIn("xp-accept", baseline)
        # Armed: /xp-accept in flight — the gate defers
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_accept_in_flight_marker_suppresses_closing(self):
        """Marker also covers the /xp-story-close window dispatched from accept."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_ONLY)
        baseline = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        baseline = self._assert_not_none(baseline)
        self.assertIn("xp-accept", baseline)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_deferred_returns_true_for_accept_in_flight(self):
        """Direct unit: _deferred honors the ACCEPT_IN_FLIGHT marker."""
        import markers
        import sprint_stop_gate

        self.assertFalse(sprint_stop_gate._deferred(self.smm_dir, "main", ""))
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        self.assertTrue(sprint_stop_gate._deferred(self.smm_dir, "main", ""))

    def test_reviewing_blocks_without_accept_in_flight(self):
        """Regression: marker absent — reviewing still blocks (safety net intact)."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)


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


class TestSprintStopGateCommitsAheadRefinement(_HookTestCase):
    """In-progress + ACCEPT marker only fires when the story branch has
    commits ahead of base — otherwise /xp-accept would verify an empty
    branch (dev-notes Item 2). The .accept marker arms on the first Edit,
    before any commit, so the marker alone isn't enough.

    Refinement applies ONLY to the in-progress+marker path: reviewing /
    closing states carry committed+merged work and fire unconditionally.
    """

    def _seed_in_progress_with_accept(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")

    def test_zero_commits_ahead_allows_stop(self):
        import sprint_stop_gate

        self._seed_in_progress_with_accept()
        with (
            patch(
                "sprint_stop_gate.branching.get_story_base_branch",
                return_value="main",
            ),
            patch("sprint_stop_gate.branching.commits_ahead", return_value=0),
        ):
            result = sprint_stop_gate.run(
                _make_stop_input(cwd=str(self.smm_dir)), smm_dir=self.smm_dir
            )
        self.assertIsNone(result)

    def test_commits_ahead_blocks(self):
        import sprint_stop_gate

        self._seed_in_progress_with_accept()
        with (
            patch(
                "sprint_stop_gate.branching.get_story_base_branch",
                return_value="main",
            ),
            patch("sprint_stop_gate.branching.commits_ahead", return_value=2),
        ):
            result = sprint_stop_gate.run(
                _make_stop_input(cwd=str(self.smm_dir)), smm_dir=self.smm_dir
            )
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_commits_ahead_unknown_blocks(self):
        """A git failure (None) is a safe default — fire rather than
        suppress, so a real un-accepted story is never silently skipped."""
        import sprint_stop_gate

        self._seed_in_progress_with_accept()
        with (
            patch(
                "sprint_stop_gate.branching.get_story_base_branch",
                return_value="main",
            ),
            patch("sprint_stop_gate.branching.commits_ahead", return_value=None),
        ):
            result = sprint_stop_gate.run(
                _make_stop_input(cwd=str(self.smm_dir)), smm_dir=self.smm_dir
            )
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_empty_cwd_blocks_without_refinement(self):
        """No cwd → can't compute commits-ahead → preserve prior behavior
        (fire). Guards the existing no-cwd accept-gate test."""
        import sprint_stop_gate

        self._seed_in_progress_with_accept()
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)


if __name__ == "__main__":
    unittest.main()
