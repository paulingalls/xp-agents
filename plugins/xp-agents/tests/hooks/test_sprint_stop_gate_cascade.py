#!/usr/bin/env python3
"""Tests for sprint_stop_gate.py cascade steps — split from test_sprint_stop_gate.py.

Covers: accept cascade (step 1), review cascade (step 2), and
ACCEPT_IN_FLIGHT suppression across the cascade.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_CLOSING_ONLY,
    SPRINT_COMPLETE_WITH_ID,
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    SPRINT_REVIEWING_ONLY,
    SPRINT_SCHEDULED_ONLY,
    _HookTestCase,
    _make_stop_input,
    _s,
    _sprint_json,
    make_event,
)
from event_schema import EVENT_TYPE_SPRINT


class TestSprintStopGateAcceptCascade(_HookTestCase):
    """Cascade step 1: accept gating."""

    def test_in_progress_with_accept_marker_blocks(self):
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
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

    def test_reviewing_only_fires_gate(self):
        """Option A (M-3): a reviewing-state story alone forces /xp-accept on
        Stop, even without the .accept marker. Teammates self-promote
        in-progress -> reviewing without orchestrator Edits, so the marker
        never arms; reviewing alone IS the signal that work needs acceptance."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_closing_only_fires_gate(self):
        """Story-005: a story stuck in `closing` (interrupted /xp-story-close)
        must still drive the user to /xp-accept on Stop. Mirrors the reviewing-
        only gate — closing is just a later phase of the same accept window.
        Without this, the user could Stop with a half-merged close and the
        cascade would silently fall through."""
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_ONLY)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_mixed_in_progress_and_closing_blocks_via_closing(self):
        """Mixed states: a teammate is mid-/xp-story-close on one story while
        siblings remain in-progress. The closing branch fires regardless of
        the marker — orchestrator must process the closing teammate before
        Stop is allowed."""
        import sprint_stop_gate

        sprint = _sprint_json(
            [
                _s("story-001", "story A closing", "closing"),
                _s("story-002", "story B still working", "in-progress"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_mixed_in_progress_and_reviewing_blocks_via_reviewing(self):
        """Mixed states: a teammate has self-promoted to reviewing while
        siblings remain in-progress. The reviewing branch fires regardless
        of the marker — orchestrator must process the reviewing teammate
        incrementally."""
        import sprint_stop_gate

        sprint = _sprint_json(
            [
                _s("story-001", "story A reviewing", "reviewing"),
                _s("story-002", "story B still working", "in-progress"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

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
        result = self._assert_not_none(result)
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

    def test_empty_stories_sprint_with_id_no_end_event_blocks(self):
        """Regression pin: empty-stories sprint with sprint_id still falls
        through to the review nudge — has_active_stories_data(empty list)
        equals is_complete's empty-stories branch (both treat as complete)."""
        import sprint_stop_gate

        empty_sprint = _sprint_json([], sprint_id="sprint-empty", started="2026-01-01")
        (self.smm_dir / "sprint.json").write_text(empty_sprint)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-sprint-review", result)

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
        result = self._assert_not_none(result)
        self.assertIn("xp-sprint-review", result)


class TestSprintStopGateAcceptInFlightConsume(_HookTestCase):
    """ACCEPT_IN_FLIGHT suppression in the Stop gate (Fix 2 / 8e0264cfcf43).

    The marker is armed by /xp-accept's preload and suppresses the accept gate
    while the skill runs (`_deferred`). The state-derived self-consume that used
    to live here was the source of the regression — /xp-accept's post-loop
    /xp-schedule promotes the NEXT frontier story to in-progress BEFORE the Stop
    fires, so the no-in-progress drain condition never held mid-sprint and the
    nudge stayed suppressed for every later story. The consume now lives at
    accept's terminal dispatch (review_cycle_done on /xp-schedule or
    /xp-sprint-review); the SessionStart sweep is the abandonment backstop. This
    gate only suppresses while the marker exists — it never self-consumes.
    """

    def test_complete_sprint_armed_marker_defers_and_keeps(self):
        """Regression pin for the removed self-consume: a complete sprint with
        the marker still armed defers (the skill is mid-flight) and KEEPS the
        marker — the gate no longer drains it from sprint state. The terminal
        /xp-sprint-review dispatch (or the SessionStart sweep) owns the drain."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")

        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

        self.assertIsNone(result)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_nudge_fires_for_later_story_once_marker_drained(self):
        """The fix's payoff: after accept's terminal dispatch drains the marker,
        a subsequent reviewing story is no longer suppressed — the accept nudge
        fires again. The regression left it suppressed for the rest of the
        session because the marker never drained mid-sprint."""
        import sprint_stop_gate

        # Marker absent (drained by /xp-schedule completion). A later teammate
        # has self-promoted to reviewing.
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

        result = self._assert_not_none(result)
        self.assertIn("xp-accept", result)

    def test_kept_with_reviewing_story(self):
        """Armed + a reviewing story → accept still in flight: defer, KEEP."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")

        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

        self.assertIsNone(result)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_kept_with_closing_story(self):
        """Armed + a closing story (no reviewing) → still mid-accept: defer,
        KEEP. The closing-window case `has_reviewing_stories` would have broken
        (reviewing count is 0 while the story is still closing) — the
        under-acceptance signal covers it."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_ONLY)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")

        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

        self.assertIsNone(result)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_kept_in_post_arm_pre_promotion_window(self):
        """The narrow window after preload arms the marker but BEFORE Step 1.0
        promotes the first story to `reviewing`: armed + zero under-acceptance
        + an in-progress story (carrying the `.accept` marker from earlier
        implementation Edits). The consume must NOT fire — accept has not
        demonstrably progressed — and the gate must NOT re-expose "run
        /xp-accept" while the skill is already running it. Empty cwd makes
        `_in_progress_has_work` return True (fire path), so this also proves
        no premature re-exposure."""
        import markers
        import sprint_stop_gate

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")

        result = sprint_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)

        # Suppressed (no re-exposure) and marker KEPT (accept still pre-promotion).
        self.assertIsNone(result)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))


if __name__ == "__main__":
    unittest.main()
