#!/usr/bin/env python3
"""Tests for xp-review-plan preload: path-based output.

Preload should output file paths (SMM_FILE, PLAN_FILE, SPRINT_FILE)
instead of dumping full file contents to stdout.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    _IntegrationTestCase,
    write_smm_fixture,
)

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-review-plan"
    / "scripts"
    / "preload.sh"
)

_SAMPLE_PLAN = """\
# Implementation Plan

## Step 1: Add user model
- File: src/models/user.py
"""


def _write_sample_smm(smm_dir):
    write_smm_fixture(
        smm_dir,
        intent=[("Ship v1", "goal")],
        constraints=[("TDD always", "convention")],
        risks=[("Auth fragile", "concern", "problem")],
        wisdom=["Commit after green"],
    )


class TestReviewPlanPreload(_IntegrationTestCase):
    """Preload outputs file paths, not content."""

    def setUp(self):
        super().setUp()
        self._plans_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self._plans_dir, ignore_errors=True)
        super().tearDown()

    def _write_plan(self, content: str = _SAMPLE_PLAN) -> Path:
        plan_file = self._plans_dir / "test-plan.md"
        plan_file.write_text(content)
        return plan_file

    def test_preload_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_smm_file_path(self):
        """SMM_FILE= path output, NOT full SMM content."""
        _write_sample_smm(self.smm_dir)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_FILE=", result.stdout)
        # Content should NOT be in stdout
        self.assertNotIn("TDD always", result.stdout)
        self.assertNotIn("Auth fragile", result.stdout)

    def test_preload_outputs_plan_file_path(self):
        """PLAN_FILE= path output, NOT full plan content."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE=", result.stdout)
        # Plan content should NOT be in stdout
        self.assertNotIn("Add user model", result.stdout)

    def test_preload_outputs_sprint_file_path(self):
        """SPRINT_FILE= path when sprint.json exists."""
        (self.smm_dir / "sprint.json").write_text("# Sprint\n- story-001")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Sprint content should NOT be in stdout
        self.assertNotIn("story-001", result.stdout)

    def test_preload_no_sprint_file_omits_path(self):
        """No SPRINT_FILE= when sprint.json doesn't exist."""
        sprint = self.smm_dir / "sprint.json"
        if sprint.exists():
            sprint.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SPRINT_FILE=", result.stdout)

    def test_preload_clears_plan_marker(self):
        """Marker file removed after preload runs."""
        plan_path = self._write_plan()
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(plan_path))
        self._run_preload(_PRELOAD_SCRIPT)
        self.assertFalse(marker.exists())

    def test_preload_no_plan_exits_ok(self):
        """No plan marker → exits 0, PLAN_FILE not in output."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preload_clean_home_no_plans_dir(self):
        """Preload exits 0 when ~/.claude/plans/ doesn't exist (CI env)."""
        clean_home = tempfile.mkdtemp()
        try:
            result = self._run_preload(_PRELOAD_SCRIPT, extra_env={"HOME": clean_home})
            self.assertEqual(
                result.returncode,
                0,
                f"Should not fail with clean HOME: {result.stderr}",
            )
            self.assertNotIn("PLAN_FILE=", result.stdout)
        finally:
            import shutil

            shutil.rmtree(clean_home, ignore_errors=True)

    def test_preload_persists_plan_path_for_assign(self):
        """Preload writes .last-plan-path for xp-assign to read."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        self._run_preload(_PRELOAD_SCRIPT)
        marker = self.smm_dir / ".last-plan-path"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text().strip(), str(plan_path))


if __name__ == "__main__":
    unittest.main()
