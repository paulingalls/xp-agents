#!/usr/bin/env python3
"""Tests for check_session_needs.sh: kickoff preload sprint-aware output."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_MIXED,
    _IntegrationTestCase,
)

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-kickoff"
    / "scripts"
    / "check_session_needs.sh"
)


class TestKickoffPreloadSprintAware(_IntegrationTestCase):
    """M8b: check_session_needs.sh outputs sprint marker and state info."""

    def test_outputs_needs_execution_plan_when_missing(self):
        """No execution_plan.md — emit NEEDS_EXECUTION_PLAN flag."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_EXECUTION_PLAN", result.stdout)

    def test_no_execution_plan_flag_when_file_exists(self):
        """execution_plan.md exists — no flag."""
        (self.smm_dir / "execution_plan.md").write_text("# Plan\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_EXECUTION_PLAN", result.stdout)

    def test_outputs_needs_sprint_when_marker_exists(self):
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_no_sprint_section_when_active_stories(self):
        """No marker, sprint.md with ready stories — no flag."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_needs_sprint_when_no_file(self):
        """No marker, no sprint.md — emit flag from file check."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_needs_sprint_when_all_done_no_marker(self):
        """No marker, sprint.md all done — emit flag."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

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
        """No markers, no sprint/spec files — flags from file-existence."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)
        # File-existence checks emit flags even without markers
        self.assertIn("NEEDS_EXECUTION_PLAN", result.stdout)
        self.assertIn("NEEDS_SPRINT", result.stdout)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_sprint_active_shows_only_ready_titles(self):
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        # Ready stories should appear
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)
        self.assertIn("2 ready stories", result.stdout)

    def test_outputs_sprint_retro_needed_when_input_exists(self):
        """M5: .sprint-retro-input.json triggers SPRINT_RETRO_NEEDED flag."""
        (self.smm_dir / ".sprint-retro-input.json").write_text('{"sprint_id": "s-1"}')
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_RETRO_NEEDED", result.stdout)

    def test_outputs_retro_needed_when_session_input_exists(self):
        """M5: .retro-input.json triggers RETRO_NEEDED flag."""
        (self.smm_dir / ".retro-input.json").write_text('{"unanalyzed_count": 6}')
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("RETRO_NEEDED", result.stdout)
        self.assertNotIn("SPRINT_RETRO_NEEDED", result.stdout)

    def test_sprint_retro_takes_precedence_when_both_exist(self):
        """M5: if both input files exist (shouldn't happen but safety),
        SPRINT_RETRO_NEEDED takes precedence and RETRO_NEEDED is suppressed."""
        (self.smm_dir / ".retro-input.json").write_text('{"unanalyzed_count": 6}')
        (self.smm_dir / ".sprint-retro-input.json").write_text('{"sprint_id": "s-1"}')
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_RETRO_NEEDED", result.stdout)
        # RETRO_NEEDED header should NOT appear as a section heading
        self.assertNotIn("### RETRO_NEEDED", result.stdout)

    def test_no_retro_flag_when_no_input_files(self):
        """M5: with neither input file, no retro flag fires."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_RETRO_NEEDED", result.stdout)
        self.assertNotIn("RETRO_NEEDED", result.stdout)

    def test_outputs_needs_system_context_when_missing(self):
        """Reports NEEDS_SYSTEM_CONTEXT when system_context.md missing."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SYSTEM_CONTEXT", result.stdout)

    def test_no_system_context_flag_when_exists(self):
        """No flag when system_context.md exists."""
        (self.smm_dir / "system_context.md").write_text("# System Context: Test")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SYSTEM_CONTEXT", result.stdout)


if __name__ == "__main__":
    unittest.main()
