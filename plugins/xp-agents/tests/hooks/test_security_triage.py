#!/usr/bin/env python3
"""Tests for xp-security-triage preload.

Preload outputs SMM_DIR and writes triage marker.
/security-review does its own diff — preload does not create a diff file.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-security-triage"
    / "scripts"
    / "preload_diff.sh"
)


class TestSecurityTriagePreload(_IntegrationTestCase):
    """Preload outputs SMM_DIR, writes marker, no diff."""

    def test_preload_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_no_diff_in_stdout(self):
        """Diff content should NOT appear in stdout."""
        (self.tmpdir / "app.py").write_text("print('hello')\n")
        subprocess.run(
            ["git", "add", "app.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("print('hello')", result.stdout)
        self.assertNotIn("DIFF_FILE=", result.stdout)

    def test_preload_no_xp_values_in_stdout(self):
        """XP values injected via SubagentStart, not preload."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Extreme Programming", result.stdout)

    def test_preload_exits_ok_with_no_changes(self):
        """No staged changes -> exits 0."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
