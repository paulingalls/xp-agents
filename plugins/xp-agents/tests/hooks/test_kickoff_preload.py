#!/usr/bin/env python3
"""Tests for check_session_needs.sh: kickoff preload sprint-aware output."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-kickoff"
    / "scripts"
    / "check_session_needs.sh"
)

SPRINT_MIXED = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: As a user I can register
- **Size:** S
- **Status:** ready
- **Dependencies:** none

### story-003: As an admin I can list users
- **Size:** L
- **Status:** ready
- **Dependencies:** story-002
"""

SPRINT_DONE_ONLY = """\
# Sprint: Build auth

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done

### story-002: As a user I can register
- **Size:** S
- **Status:** deferred
"""


class TestKickoffPreloadSprintAware(_IntegrationTestCase):
    """M8b: check_session_needs.sh outputs sprint marker and state info."""

    def _run_preload(self) -> subprocess.CompletedProcess:
        """Run check_session_needs.sh as a subprocess."""
        if not _PRELOAD_SCRIPT.is_file():
            self.skipTest("check_session_needs.sh not yet created")
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)
        return subprocess.run(
            ["bash", str(_PRELOAD_SCRIPT)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_outputs_needs_product_spec_when_marker_exists(self):
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_PRODUCT_SPEC", result.stdout)

    def test_no_product_spec_section_without_marker(self):
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_PRODUCT_SPEC", result.stdout)

    def test_outputs_needs_sprint_when_marker_exists(self):
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_no_sprint_section_without_marker(self):
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_sprint_active_when_ready_stories(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_ACTIVE", result.stdout)
        self.assertIn("story-002", result.stdout)

    def test_no_sprint_active_when_no_sprint_file(self):
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_sprint_active_when_all_done(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_DONE_ONLY)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_markers_no_sprint(self):
        """No markers, no sprint — clean output with SMM_DIR only."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)
        # Should NOT have conditional sections
        self.assertNotIn("NEEDS_PRODUCT_SPEC", result.stdout)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_sprint_active_shows_only_ready_titles(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        # Ready stories should appear
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)
        self.assertIn("2 ready stories", result.stdout)


if __name__ == "__main__":
    unittest.main()
