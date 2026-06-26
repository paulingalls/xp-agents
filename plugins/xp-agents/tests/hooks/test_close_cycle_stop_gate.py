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
        stderr right now."""
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
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

    def test_bypass_keeps_young_marker(self):
        """Young marker (< threshold) stays put on bypass — preserves
        the safety net for a genuine in-progress cycle when
        stop_hook_active was latched by an unrelated earlier hook
        (concern 07ab750a5487)."""
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
        self.assertEqual(len(concerns), 1)

    def test_bypass_consumes_old_marker(self):
        """Old marker (>= threshold) is consumed — cycle empirically
        abandoned, avoids re-firing the gate on every subsequent Stop."""
        import os

        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        marker_path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        backdate_sec = close_cycle_stop_gate._CLOSE_CYCLE_AGE_THRESHOLD_SEC + 60
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

    def test_bypass_records_concern_even_when_mid_cycle(self):
        """Fix 1: mid-cycle suppression must not swallow abandonment detection.
        A stop_hook_active latch during the Step 4b window still records the
        high-severity bypass concern — only the in-flight nudge is suppressed,
        not the abandonment signal."""
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
        self.assertEqual(len(concerns), 1, "abandonment concern must still record")
        self.assertEqual(concerns[0]["severity"], "high")

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
