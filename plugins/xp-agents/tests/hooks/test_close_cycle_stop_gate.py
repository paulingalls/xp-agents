#!/usr/bin/env python3
"""Tests for close_cycle_stop_gate.py — close-cycle Stop gate.

Mirrors sprint_stop_gate.py shape but with a single block trigger:
the CLOSE_CYCLE_ACTIVE marker. ASKING_USER deferral preserves
AskUserQuestion dialogue flow; review-cycle/teammates deferrals are
intentionally NOT applied (close cycle wants to block mid-cycle).
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
