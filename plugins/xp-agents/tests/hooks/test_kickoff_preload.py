#!/usr/bin/env python3
"""Tests for check_session_needs.sh: kickoff preload sprint-aware output."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import SPRINT_ALL_DONE, SPRINT_MIXED, _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-kickoff"
    / "scripts"
    / "check_session_needs.sh"
)


class TestKickoffPreloadSprintAware(_IntegrationTestCase):
    """M8b: check_session_needs.sh outputs sprint marker and state info."""

    def test_outputs_needs_product_spec_when_marker_exists(self):
        (self.smm_dir / ".needs-product-spec").write_text("startup")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_PRODUCT_SPEC", result.stdout)

    def test_no_product_spec_section_without_marker(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_PRODUCT_SPEC", result.stdout)

    def test_outputs_needs_sprint_when_marker_exists(self):
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_no_sprint_section_without_marker(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_sprint_active_when_ready_stories(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_ACTIVE", result.stdout)
        self.assertIn("story-002", result.stdout)

    def test_no_sprint_active_when_no_sprint_file(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_sprint_active_when_all_done(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_markers_no_sprint(self):
        """No markers, no sprint — clean output with SMM_DIR only."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)
        # Should NOT have conditional sections
        self.assertNotIn("NEEDS_PRODUCT_SPEC", result.stdout)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_sprint_active_shows_only_ready_titles(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        # Ready stories should appear
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)
        self.assertIn("2 ready stories", result.stdout)


if __name__ == "__main__":
    unittest.main()
