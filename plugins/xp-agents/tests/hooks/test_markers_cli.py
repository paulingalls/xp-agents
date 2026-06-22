#!/usr/bin/env python3
"""Tests for markers.py generic CLI: write|consume <NAME>.

Resolves marker name via getattr(markers, name). Used by close-skill
prose to write CLOSE_CYCLE_ACTIVE before /security-review and by tests
to drive marker state in subprocess.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _MARKERS_PY, _HookTestCase, run_cli


class TestMarkersCLI(_HookTestCase):
    def test_write_creates_marker(self):
        result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".close-cycle-active").exists())

    def test_write_idempotent(self):
        for _ in range(2):
            result = run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".close-cycle-active").exists())

    def test_consume_removes_marker(self):
        run_cli(_MARKERS_PY, ["write", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.smm_dir / ".close-cycle-active").exists())

    def test_consume_when_absent_succeeds(self):
        result = run_cli(_MARKERS_PY, ["consume", "CLOSE_CYCLE_ACTIVE"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_marker_name_errors(self):
        """Marker names not in _CLI_ALLOWLIST are rejected by argparse choices."""
        result = run_cli(
            _MARKERS_PY, ["write", "DEFINITELY_NOT_A_MARKER"], self.smm_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEFINITELY_NOT_A_MARKER", result.stderr)

    def test_non_allowlisted_marker_errors(self):
        """Even valid MarkerDefs are rejected if not in _CLI_ALLOWLIST.

        ASSIGN_PENDING is a real non-agent-scoped MarkerDef but is
        intentionally NOT exposed via the CLI — its writer is a hook.
        """
        result = run_cli(_MARKERS_PY, ["write", "ASSIGN_PENDING"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_consume_accept_in_flight(self):
        """xp-accept's terminal Summary step disarms the marker via the CLI."""
        result = run_cli(_MARKERS_PY, ["consume", "ACCEPT_IN_FLIGHT"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.smm_dir / ".accept-in-flight").exists())


if __name__ == "__main__":
    unittest.main()
