#!/usr/bin/env python3
"""Tests for M15: xp-spawn-team preload integration.

Covers: preload.sh output (SMM, sprint, plan, guide), graceful degradation.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-spawn-team"
    / "scripts"
    / "preload.sh"
)

_SAMPLE_SPRINT = """\
# Sprint: Build user management REST API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: User registration
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
"""

_SAMPLE_PLAN = """\
# Implementation Plan

## Step 1: Add user model
- File: src/models/user.py
- Tests: tests/test_user.py

## Step 2: Add auth endpoints
- File: src/api/auth.py
- Tests: tests/test_auth.py
"""


class TestSpawnTeamPreload(_IntegrationTestCase):
    """M15: preload.sh dumps SMM + sprint + plan + guide."""

    def setUp(self):
        super().setUp()
        # Create a temp plans directory to avoid polluting real ~/.claude/plans/
        self._plans_dir = Path(tempfile.mkdtemp())
        self._orig_home = os.environ.get("HOME")

    def tearDown(self):
        # Clean up temp plans
        import shutil

        shutil.rmtree(self._plans_dir, ignore_errors=True)
        super().tearDown()

    def _write_plan(self, content: str = _SAMPLE_PLAN) -> Path:
        """Write a plan file to a temp location and return its path."""
        plan_file = self._plans_dir / "test-plan.md"
        plan_file.write_text(content)
        return plan_file

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_plan_file_path(self):
        """PLAN_FILE= path output, NOT full plan content."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE=", result.stdout)
        # Plan content should NOT be in stdout
        self.assertNotIn("Add user model", result.stdout)

    def test_preload_outputs_file_paths_not_content(self):
        """SMM_FILE=, SPRINT_FILE= paths, NOT pillar/sprint content."""
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text(
            "# Shared Mental Model\n\n"
            "## Constraints\n- TDD always\n\n"
            "## Wisdom\n- Commit after green\n"
        )
        (self.smm_dir / "sprint.md").write_text(_SAMPLE_SPRINT)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_FILE=", result.stdout)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Content should NOT be in stdout
        self.assertNotIn("TDD always", result.stdout)
        self.assertNotIn("Commit after green", result.stdout)
        self.assertNotIn("sprint-001", result.stdout)

    def test_preload_no_marker_exits_ok(self):
        """No plan marker -> exits 0."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
