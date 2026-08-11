#!/usr/bin/env python3
"""Tests for close_cycle_stop_gate.py — deferral/release conditions.

Split from test_close_cycle_stop_gate.py by test-class grouping: this file
covers the conditions that override the base block — evidence-based release
(a close-reviewer subagent_complete after close_started releases a lingering
CLOSE_CYCLE_ACTIVE marker) and the age-bounded Step 4b mid-cycle defer (young
marker defers, aged marker blocks instead of latching off forever). See
test_close_cycle_stop_gate_core.py for the base block/no-block/bypass
behavior and the hooks.json registration check.

Mirrors sprint_stop_gate.py shape but with a single block trigger:
the CLOSE_CYCLE_ACTIVE marker. ASKING_USER deferral preserves
AskUserQuestion dialogue flow; the review-mid-cycle deferral applies
only inside the close /code-review's Step 4b window (review_records.review_mid_cycle)
so the close-reviewer nudge waits for the async workflow — otherwise the
close cycle wants to block mid-cycle. Teammates deferral is NOT applied.
"""

import sys
import unittest
from pathlib import Path

import review_records

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_stop_input, make_event
from event_schema import EVENT_TYPE_STATUS


def _seed_status(smm_dir, action: str, agent_type: str = "") -> None:
    """Append a status event carrying metadata.action (+ optional agent_type).

    Templates test_sprint_stop_gate._seed_sprint_end: the close-cycle evidence
    check reads log-append order, so seeding real events exercises the same
    path the gate walks.
    """
    import _common

    metadata = {"action": action}
    if agent_type:
        metadata["agent_type"] = agent_type
    event = make_event(
        EVENT_TYPE_STATUS,
        agent_id="seed",
        content=f"seed {action}",
        working_on=[],
        metadata=metadata,
    )
    _common.append_safe(smm_dir, event)


class TestCloseCycleEvidenceRelease(_HookTestCase):
    """story-002 Part 2: reviewer-completion evidence RELEASES a lingering marker.

    The block stays marker-triggered; a subagent_complete event whose
    agent_type resolves to xp-close-reviewer, appearing AFTER the latest
    close_started, proves a reviewer ran this cycle and overrides the block.
    """

    def test_evidence_after_close_started_releases_marker(self):
        """AC #2: marker present + close_started anchor + close-reviewer
        subagent_complete after it → gate releases (returns None)."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_evidence_matches_qualified_agent_type(self):
        """The agent_type resolves via strip_our_namespace, so the
        xp-agents:-qualified form releases too."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(
            self.smm_dir,
            "subagent_complete",
            agent_type="xp-agents:xp-close-reviewer",
        )

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_evidence_before_close_started_still_blocks(self):
        """Ordering matters: a close-reviewer completion from a PRIOR cycle
        (before the latest close_started) is not this cycle's evidence — the
        gate still blocks."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        # Prior-cycle reviewer completion, THEN a fresh close_started with no
        # subsequent reviewer completion.
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")
        _seed_status(self.smm_dir, "close_started")

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_no_close_started_anchor_still_blocks(self):
        """A close-reviewer completion with NO close_started anchor cannot be
        attributed to the current cycle → block (fail toward surfacing)."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_other_agent_completion_does_not_release(self):
        """A non-reviewer subagent_complete after close_started is not
        evidence a REVIEWER ran — the gate still blocks."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="general-purpose")

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_evidence_releases_before_stop_hook_bypass(self):
        """Placement AC (#5 crash path): evidence + a lingering marker aged
        past the abandonment timeout, on a stop_hook_active Stop, must RELEASE
        (return None) WITHOUT recording a false abandonment concern. The
        release guard runs BEFORE the bypass, so the crash-left lingering
        marker (Part 1 emits evidence then consumes; a crash between leaves
        both) never gets mis-recorded as 'reviewer never ran'."""
        import os

        import close_cycle_abandonment
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate = close_cycle_abandonment.ABANDONMENT_MIN_AGE_SEC + 60
        old = marker_path.stat().st_mtime - backdate
        os.utime(marker_path, (old, old))

        result = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            len(concerns),
            0,
            "evidence release must pre-empt the bypass — no false abandonment concern",
        )

    def test_the_release_consumes_the_marker(self):
        """Allowing the Stop is not releasing. The marker outlives the session
        that held the evidence, and the next thing to find it — the
        SessionStart sweep — asks the shared recorder with no evidence check of
        its own, so a survivor becomes the false high-severity 'close
        abandoned' concern this branch exists to prevent."""
        import close_cycle_stop_gate
        import markers
        import session_markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")

        self.assertIsNone(
            close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "the evidence release must consume the marker, not just allow the stop",
        )

        session_markers.sweep_stale_session_markers(self.smm_dir)
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            concerns, [], "a reviewed cycle must not be swept as abandoned later"
        )

    def test_a_release_with_no_evidence_leaves_the_marker_for_the_sweep(self):
        """Non-vacuity for the consume: without evidence nothing is released,
        so a genuinely abandoned cycle still reaches the sweep."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")

        self.assertIsNotNone(
            close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        )
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))

    def test_fail_closed_on_corrupt_read_still_blocks(self):
        """AC #5: a failed event read is treated as no-evidence → the gate
        still blocks, never a silent release, never a crash."""
        from unittest.mock import patch

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        _seed_status(self.smm_dir, "close_started")
        _seed_status(self.smm_dir, "subagent_complete", agent_type="xp-close-reviewer")

        with patch(
            "close_cycle_stop_gate._common.load_events_with_resolutions",
            side_effect=OSError("corrupt events.jsonl"),
        ):
            result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_helper_returns_false_on_bad_read(self):
        """reviewer_completed_this_cycle itself fails closed (returns False)
        rather than raising into the Stop hook."""
        from unittest.mock import patch

        import close_cycle_stop_gate

        with patch(
            "close_cycle_stop_gate._common.load_events_with_resolutions",
            side_effect=ValueError("boom"),
        ):
            self.assertFalse(
                close_cycle_stop_gate.reviewer_completed_this_cycle(self.smm_dir)
            )


class TestCloseCycleMidCycleAgeGate(_HookTestCase):
    """Fix 1: the review_mid_cycle defer is age-bounded.

    The Step 4b defer (mid-cycle + young marker) is legitimate — the async
    /code-review workflow is plausibly still running. But if /xp-quality-review
    never sets quality_review_done (interrupted/errored consume), review_mid_cycle
    stays True on every Stop and the unbounded defer silently abandons the close
    (CLOSE_CYCLE_ACTIVE stuck, security-review + close-reviewer never run). Bound
    the defer to its own window: once the marker is older than that, the consume
    is stuck — block instead of defer, so the close is surfaced rather than
    silently dropped.

    `_arm_mid_cycle` arms with an owner id nothing heartbeats, which is the
    older-version / unresolvable-session case: the one where age still decides.
    A marker armed by `arm_close_cycle` in a LIVE session is never recorded
    against however old it is — `test_close_cycle_owner_liveness.py` owns both
    directions of that rule.
    """

    def _arm_mid_cycle(self) -> dict:
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        review_records.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        return input_data

    def _backdate_marker(self) -> None:
        import os

        import close_cycle_abandonment
        import markers

        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate = close_cycle_abandonment.ABANDONMENT_MIN_AGE_SEC + 60
        old = marker_path.stat().st_mtime - backdate
        os.utime(marker_path, (old, old))

    def test_aged_marker_mid_cycle_blocks_not_defers(self):
        """Aged marker + mid-cycle → the stuck consume no longer latches the gate
        off: it blocks (nudges the close-reviewer) instead of deferring."""
        import close_cycle_stop_gate

        input_data = self._arm_mid_cycle()
        self._backdate_marker()

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_aged_mid_cycle_then_bypass_unsticks(self):
        """Full unstick for an UNOWNED marker: aged + mid-cycle blocks, then the
        NEXT Stop (stop_hook_active latched) consumes the now-aged marker AND
        records the abandonment concern — the gate doesn't block every Stop
        forever. An owned marker whose session still answers is the other rule;
        see the class docstring."""
        import close_cycle_stop_gate
        import markers

        input_data = self._arm_mid_cycle()
        self._backdate_marker()

        # First Stop: blocks (no longer defers), marker still present.
        blocked = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNotNone(blocked)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))

        # Next Stop with stop_hook_active latched: bypass consumes the aged
        # marker and records the abandonment concern.
        bypassed = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
        )
        self.assertIsNone(bypassed)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "aged marker must be consumed on the bypass — gate unsticks",
        )
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_young_marker_mid_cycle_still_defers(self):
        """Regression: a young marker (workflow plausibly still running) +
        mid-cycle still defers — the legitimate Step 4b wait is preserved."""
        import close_cycle_stop_gate

        input_data = self._arm_mid_cycle()  # marker just written → young

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_long_running_workflow_under_threshold_still_defers(self):
        """Regression for the outdated 600s bound: an async /code-review high
        workflow routinely runs 10-15 min. A marker aged ~15 min (well past the
        former 600s threshold, but under the current one) must STILL defer — the
        old bound expired mid-Step-4b and re-fired the premature close-reviewer
        nudge the defer exists to prevent."""
        import os

        import close_cycle_stop_gate
        import markers

        input_data = self._arm_mid_cycle()
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        # 900s old: > the retired 600s bound, < the current defer window.
        assert close_cycle_stop_gate._CLOSE_CYCLE_DEFER_WINDOW_SEC > 900
        old = marker_path.stat().st_mtime - 900
        os.utime(marker_path, (old, old))

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stat_race_in_defer_path_blocks(self):
        """A stat() race (marker vanished between marker_exists and the age read)
        is treated as NOT young — block, never silently latch off. Fail toward
        surfacing. Simulated by making marker_exists lie 'present' for
        CLOSE_CYCLE_ACTIVE only (ASKING_USER must still be False) with no file on
        disk, so the age read's stat() raises. The review flag is written for
        real so review_mid_cycle (which reads the review-cycle marker, not
        marker_exists) is genuinely True."""
        from unittest.mock import patch

        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        review_records.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        def _selective(_smm_dir, marker, _agent_id=""):
            return marker == markers.CLOSE_CYCLE_ACTIVE

        with patch(
            "close_cycle_stop_gate.markers.marker_exists",
            side_effect=_selective,
        ):
            result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)


if __name__ == "__main__":
    unittest.main()
