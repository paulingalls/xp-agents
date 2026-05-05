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

from conftest import _HookTestCase, run_cli

_MARKERS_PY = Path(__file__).parent.parent.parent / "scripts" / "markers.py"


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
        result = run_cli(
            _MARKERS_PY, ["write", "DEFINITELY_NOT_A_MARKER"], self.smm_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEFINITELY_NOT_A_MARKER", result.stderr)

    def test_agent_scoped_marker_errors(self):
        """Agent-scoped markers (e.g. TDD_TRACKER) need agent_id; CLI rejects."""
        result = run_cli(_MARKERS_PY, ["write", "TDD_TRACKER"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
