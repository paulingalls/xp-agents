#!/usr/bin/env python3
"""Tests for xp-security-triage preload: path-based diff output.

Preload should write diff to a file and output DIFF_FILE=<path>
instead of dumping full diff content to stdout.
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
    """Preload writes diff to file, outputs path."""

    def _stage_file(self, name: str = "test_code.py", content: str = "x = 1\n"):
        (self.tmpdir / name).write_text(content)
        subprocess.run(
            ["git", "add", name],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def test_preload_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_diff_file_path(self):
        """DIFF_FILE= path output, NOT full diff content."""
        self._stage_file()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DIFF_FILE=", result.stdout)

    def test_diff_file_contains_content(self):
        """The diff file should contain actual diff output."""
        self._stage_file("app.py", "print('hello')\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        diff_path = None
        for line in result.stdout.splitlines():
            if line.startswith("DIFF_FILE="):
                diff_path = line.split("=", 1)[1]
                break
        self.assertIsNotNone(diff_path, "DIFF_FILE= not in output")
        content = Path(diff_path).read_text()
        self.assertIn("app.py", content)

    def test_diff_content_not_in_stdout(self):
        """Diff content should NOT appear directly in stdout."""
        self._stage_file("app.py", "print('hello')\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("print('hello')", result.stdout)

    def test_preload_exits_ok_with_no_changes(self):
        """No staged changes -> exits 0."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
