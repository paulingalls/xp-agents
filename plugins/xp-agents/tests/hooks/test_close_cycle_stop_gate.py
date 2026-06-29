#!/usr/bin/env python3
"""Tests for close_cycle_stop_gate.py — close-cycle Stop gate.

Mirrors sprint_stop_gate.py shape but with a single block trigger:
the CLOSE_CYCLE_ACTIVE marker. ASKING_USER deferral preserves
AskUserQuestion dialogue flow; the review-mid-cycle deferral applies
only inside the close /code-review's Step 4b window (markers.review_mid_cycle)
so the close-reviewer nudge waits for the async workflow — otherwise the
close cycle wants to block mid-cycle. Teammates deferral is NOT applied.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _hooks_json import HooksJsonTestCase
from conftest import _HookTestCase, _make_stop_input


class TestCloseCycleStopGate(_HookTestCase):
    """Block when CLOSE_CYCLE_ACTIVE marker is present, else pass-through."""

    def test_blocks_when_marker_present(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_block_message_names_all_three_close_phases(self):
        # The mid-flight nudge must name every step the agent should run, in
        # the canonical close-skill order: /security-review (Step 4),
        # /code-review high (Step 4b, gated on RUN_FULL_CODE_REVIEW=true),
        # then xp-close-reviewer (Step 4.5). The earlier message omitted
        # /code-review high, so an agent re-entering the close cycle could
        # read it as "skip Step 4b" — but post-merge there's no diff, so
        # /code-review must run pre-merge or never. Order matters because the
        # agent follows the nudge sequentially: /security-review precedes
        # /code-review in the close skill, and the close-reviewer comes last.
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("/code-review", result)
        self.assertIn("/security-review", result)
        self.assertIn("xp-close-reviewer", result)
        # `/code-review high` is load-bearing — bare `/code-review` would
        # default to a lower effort and skip the full pre-merge workflow.
        self.assertIn("/code-review high", result)
        # Canonical order: security-review (Step 4) → code-review (Step 4b)
        # → close-reviewer (Step 4.5). Substring positions enforce it.
        sec = result.index("/security-review")
        code = result.index("/code-review")
        reviewer = result.index("xp-close-reviewer")
        self.assertLess(
            sec,
            code,
            "/security-review (Step 4) must precede /code-review (Step 4b)",
        )
        self.assertLess(
            code,
            reviewer,
            "/code-review (Step 4b) must precede xp-close-reviewer (Step 4.5)",
        )

    def test_no_block_when_marker_absent(self):
        import close_cycle_stop_gate

        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_block_when_xp_agent(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(
            _make_stop_input(agent_type="xp-nav"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_no_block_when_stop_hook_active(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_bypass_records_high_severity_concern_with_recovery_hint(self):
        """Bypass (stop_hook_active=True + marker) must escalate to severity=high
        and include a recovery instruction in both the concern content and
        stderr — so xp-end-session's high-severity 'watch' surfaces it next
        session and the terminating agent leaves a visible breadcrumb on
        stderr right now. Only an AGED marker (truly abandoned) records; a
        young in-flight marker is left alone (see the mid-cycle test)."""
        import os

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
        old = marker_path.stat().st_mtime - backdate
        os.utime(marker_path, (old, old))
        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf):
            result = close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1, "exactly one bypass concern expected")
        concern = concerns[0]
        self.assertEqual(concern["severity"], "high")
        self.assertIn("Recovery:", concern["content"])
        self.assertIn("xp-close-reviewer", concern["content"])

        stderr = stderr_buf.getvalue()
        self.assertIn("Recovery:", stderr)
        self.assertIn("xp-close-reviewer", stderr)

    def test_bypass_keeps_young_marker_and_records_no_concern(self):
        """Young marker (< threshold) on bypass is a live in-flight cycle: the
        marker stays put AND no abandonment concern is recorded — recording one
        for a young (e.g. Step 4b async-wait) yield is a false positive. The
        SessionStart sweep is the backstop if a young cycle is truly abandoned."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )

        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "young marker must be preserved on bypass",
        )
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            len(concerns),
            0,
            "young in-flight marker must NOT record an abandonment concern",
        )

    def test_bypass_consumes_old_marker(self):
        """Old marker (>= threshold) is consumed — cycle empirically
        abandoned, avoids re-firing the gate on every subsequent Stop."""
        import os

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate_sec = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
        old_mtime = marker_path.stat().st_mtime - backdate_sec
        os.utime(marker_path, (old_mtime, old_mtime))

        close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True),
            smm_dir=self.smm_dir,
        )

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "old marker must be consumed on bypass",
        )
        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)

    def test_bypass_handles_stat_race_without_crashing(self):
        """If the marker vanishes between marker_exists() and stat()
        (theoretical race; rare in practice), the gate still records the
        concern + stderr but skips the consume cleanly. Simulated by
        making marker_exists lie 'present' for CLOSE_CYCLE_ACTIVE only
        (ASKING_USER must still return False) — stat() then raises
        FileNotFoundError because no file was written to disk."""
        from unittest.mock import patch

        import close_cycle_stop_gate
        import markers

        def _selective_marker_exists(_smm_dir, marker, _agent_id=""):
            return marker == markers.CLOSE_CYCLE_ACTIVE

        with patch(
            "close_cycle_stop_gate.markers.marker_exists",
            side_effect=_selective_marker_exists,
        ):
            close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True),
                smm_dir=self.smm_dir,
            )

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)

    def test_no_block_during_step_4b_review_mid_cycle(self):
        """Fix 1: during Step 4b the close /code-review workflow is in flight
        (simplify_done set when it launched, quality_review_done not yet set).
        The gate must NOT push xp-close-reviewer — Step 4.5 comes AFTER the
        async workflow returns and /xp-quality-review (consume-findings)
        validates its findings. Defer (return None) so the agent yields and is
        re-woken by the workflow-completion notification.

        Same-key keying: the flag is written under the SAME agent_id the gate
        resolves via identity.resolve_agent_id — mirroring sprint_stop_gate."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_blocks_after_quality_review_done(self):
        """Fix 1 regression: once /xp-quality-review sets quality_review_done
        (Step 4b complete) the cycle is no longer mid-flight — the gate
        resumes nudging xp-close-reviewer."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.write_review_cycle(
            self.smm_dir,
            agent_id,
            {
                "simplify_done": True,
                "quality_review_done": True,
                "last_review_commit": "abc123",
            },
        )

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_blocks_before_step_4b_neither_flag(self):
        """Fix 1 regression: before Step 4b (no review flags set) the cycle is
        not mid-flight — the gate still nudges. Only the in-flight window is
        suppressed."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        # quality_review_done WITHOUT simplify_done is a completed self-find
        # review, not mid-cycle — must NOT suppress (the load-bearing invariant
        # shared with sprint_stop_gate).
        markers.set_review_flag(self.smm_dir, agent_id, "quality_review_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)

    def test_bypass_during_step_4b_records_no_spurious_concern(self):
        """A stop_hook_active latch during the Step 4b window (young marker,
        simplify_done set, agent yielding for the async /code-review) must NOT
        record an abandonment concern — that was the false positive: stop_hook_active
        is usually already latched session-wide by close time, so a legitimate
        Step 4b yield would otherwise log a spurious high-severity 'close
        abandoned' concern even though the workflow notification re-wakes the
        agent and the close finishes. The young marker is left intact."""
        import close_cycle_stop_gate
        import identity
        import markers

        input_data = _make_stop_input(stop_hook_active=True)
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        self.assertIsNone(result)

        concerns = [e for e in self._read_events() if e.get("type") == "concern"]
        self.assertEqual(
            len(concerns), 0, "young Step 4b yield must not record a spurious concern"
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "young marker preserved through the Step 4b yield",
        )

    def test_bypass_concern_content_fits_concern_budget(self):
        """The bypass concern content + the recovery hint together must stay
        under the concern event's CONTENT_BUDGET (400 chars). append_safe
        silently drops over-budget events — pre-this-test, extending
        _BYPASS_RECOVERY pushed the content to ~440 chars and the bypass
        concern stopped landing, breaking abandonment surfacing entirely.
        Pin the budget so future recovery-string edits fail this test
        loudly before they ship."""
        import close_cycle_stop_gate
        from event_schema import CONTENT_BUDGETS, EVENT_TYPE_CONCERN

        budget = self._assert_not_none(
            CONTENT_BUDGETS[EVENT_TYPE_CONCERN],
            "concern budget must remain enforced",
        )
        self.assertLessEqual(
            len(close_cycle_stop_gate._BYPASS_CONCERN_CONTENT),
            budget,
            "_BYPASS_CONCERN_CONTENT must fit the concern budget — otherwise "
            "append_safe silently drops the bypass concern and abandonment "
            "never surfaces",
        )

    def test_no_block_when_asking_user(self):
        """Defer when AskUserQuestion dialogue is in flight."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.marker_write(self.smm_dir, markers.ASKING_USER, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_passes_through(self):
        import close_cycle_stop_gate

        result = close_cycle_stop_gate.run(
            _make_stop_input(), smm_dir=Path("/nonexistent/smm")
        )
        self.assertIsNone(result)


class TestCloseCycleMidCycleAgeGate(_HookTestCase):
    """Fix 1: the review_mid_cycle defer is age-bounded.

    The Step 4b defer (mid-cycle + young marker) is legitimate — the async
    /code-review workflow is plausibly still running. But if /xp-quality-review
    never sets quality_review_done (interrupted/errored consume), review_mid_cycle
    stays True on every Stop and the unbounded defer silently abandons the close
    (CLOSE_CYCLE_ACTIVE stuck, security-review + close-reviewer never run). Bound
    the defer to the same age threshold _record_bypass uses: once the marker is
    older than the threshold the consume is stuck — block instead of defer, so the
    next stop_hook_active bypass consumes the marker and records the abandonment
    concern.
    """

    def _arm_mid_cycle(self) -> dict:
        import identity
        import markers

        input_data = _make_stop_input()
        agent_id = identity.resolve_agent_id(input_data)
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")
        return input_data

    def _backdate_marker(self) -> None:
        import os

        import close_cycle_stop_gate
        import markers

        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate = close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC + 60
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
        """Full unstick: aged marker + mid-cycle blocks, then the NEXT Stop
        (stop_hook_active latched) consumes the now-aged marker AND records the
        abandonment concern — the gate doesn't just block every Stop forever."""
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
        markers.set_review_flag(self.smm_dir, agent_id, "simplify_done")

        def _selective(_smm_dir, marker, _agent_id=""):
            return marker == markers.CLOSE_CYCLE_ACTIVE

        with patch(
            "close_cycle_stop_gate.markers.marker_exists",
            side_effect=_selective,
        ):
            result = close_cycle_stop_gate.run(input_data, smm_dir=self.smm_dir)
        result = self._assert_not_none(result)
        self.assertIn("xp-close-reviewer", result)


class TestCloseCycleStopGateRegistration(HooksJsonTestCase):
    """Hook is registered in hooks.json Stop array between sprint_stop_gate
    and housekeeping_stop_gate."""

    def test_registered_in_hooks_json(self):
        stop_entries = self.data["hooks"].get("Stop", [])
        self.assertEqual(len(stop_entries), 1, "Single Stop entry expected")
        commands = [h.get("command", "") for h in stop_entries[0].get("hooks", [])]
        names = [
            Path(next(t for t in c.split() if t.endswith(".py"))).name for c in commands
        ]
        self.assertIn("close_cycle_stop_gate.py", names)
        i_close = names.index("close_cycle_stop_gate.py")
        i_sprint = names.index("sprint_stop_gate.py")
        i_housekeeping = names.index("housekeeping_stop_gate.py")
        self.assertLess(i_sprint, i_close)
        self.assertLess(i_close, i_housekeeping)


if __name__ == "__main__":
    unittest.main()
