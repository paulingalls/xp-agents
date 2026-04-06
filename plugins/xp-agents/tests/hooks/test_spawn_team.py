#!/usr/bin/env python3
"""Tests for M15: xp-spawn-team preload integration.

Covers: preload.sh output (SMM, sprint, plan, guide), graceful degradation.
"""

import os
import subprocess
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

    def _run_preload(
        self,
        extra_env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        """Run preload.sh as a subprocess."""
        if not _PRELOAD_SCRIPT.is_file():
            self.skipTest("preload.sh not yet created")
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(_PRELOAD_SCRIPT)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_plan_content(self):
        """Preload output includes current plan content."""
        plan_path = self._write_plan()
        # Point the marker to our plan
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Current Plan", result.stdout)
        self.assertIn("Add user model", result.stdout)

    def test_preload_has_smm_pillars_and_sprint(self):
        """Preload includes Constraints/Wisdom pillars + sprint.md."""
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text(
            "# Shared Mental Model\n\n"
            "## Intent\n- Ship v1\n\n"
            "## Constraints\n- TDD always\n\n"
            "## Risks\n- Auth fragile\n\n"
            "## Wisdom\n- Commit after green\n"
        )
        (self.smm_dir / "sprint.md").write_text(_SAMPLE_SPRINT)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Should have Constraints and Wisdom
        self.assertIn("TDD always", result.stdout)
        self.assertIn("Commit after green", result.stdout)
        # Should NOT have Intent or Risks
        self.assertNotIn("Ship v1", result.stdout)
        self.assertNotIn("Auth fragile", result.stdout)
        # Should have sprint content
        self.assertIn("sprint-001", result.stdout)
        # Verify values are not injected as a preload section
        # (plan content may contain "XP Values" as text — only check
        # that the output before "## Current Plan" has no values header)
        before_plan = result.stdout.split("## Current Plan")[0]
        self.assertNotIn("## XP Values", before_plan)

    def test_preload_no_marker_exits_ok(self):
        """No plan marker -> exits 0, falls back to glob or shows not-found."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Should have either plan content (from glob) or not-found message
        self.assertIn("plan", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
