#!/usr/bin/env python3
"""Tests for xp-quality-review preload."""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-quality-review"
    / "scripts"
    / "preload.sh"
)


class TestQualityReviewPreload(_IntegrationTestCase):
    """M13: preload shows uncommitted changes, not previous commit."""

    def test_preload_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_shows_uncommitted_changes(self):
        """Preload should show uncommitted file modifications, not HEAD~1."""
        # Create and commit a file
        (self.tmpdir / "old.py").write_text("old content")
        subprocess.run(
            ["git", "add", "old.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add old"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Modify the file (uncommitted)
        (self.tmpdir / "old.py").write_text("new content")

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("old.py", result.stdout)

    def test_preload_shows_new_untracked_files(self):
        """Preload should include new untracked files in changed files list."""
        (self.tmpdir / "brand_new.py").write_text("new file")

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("brand_new.py", result.stdout)

    def test_preload_shows_staged_changes(self):
        """Preload should show staged but uncommitted changes."""
        (self.tmpdir / "staged.py").write_text("staged content")
        subprocess.run(
            ["git", "add", "staged.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("staged.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
