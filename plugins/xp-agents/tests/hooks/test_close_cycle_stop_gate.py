#!/usr/bin/env python3
"""Tests for close_cycle_stop_gate.py — close-cycle Stop gate.

Mirrors sprint_stop_gate.py shape but with a single block trigger:
the CLOSE_CYCLE_ACTIVE marker. ASKING_USER deferral preserves
AskUserQuestion dialogue flow; review-cycle/teammates deferrals are
intentionally NOT applied (close cycle wants to block mid-cycle).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_stop_input


class TestCloseCycleStopGate(_HookTestCase):
    """Block when CLOSE_CYCLE_ACTIVE marker is present, else pass-through."""

    def test_blocks_when_marker_present(self):
        import close_cycle_stop_gate
        import markers

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        result = close_cycle_stop_gate.run(_make_stop_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("close-reviewer next", result)

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


if __name__ == "__main__":
    unittest.main()
