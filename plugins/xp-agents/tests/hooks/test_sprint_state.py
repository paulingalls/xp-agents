#!/usr/bin/env python3
"""Tests for sprint_state.py: sprint and planning document state helpers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_IN_PROGRESS,
    SPRINT_MIXED_IN_PROGRESS,
    SPRINT_READY_ONLY,
    _HookTestCase,
)


class TestHasActiveStories(unittest.TestCase):
    """Test has_active_stories — checks for ready or in-progress."""

    def test_ready_story(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_READY_ONLY))

    def test_in_progress_story(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_IN_PROGRESS))

    def test_done_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_active_stories(SPRINT_ALL_DONE))

    def test_empty_string(self):
        import sprint_state

        self.assertFalse(sprint_state.has_active_stories(""))

    def test_mixed_statuses(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_MIXED_IN_PROGRESS))


class TestHasInProgressStories(unittest.TestCase):
    """Test has_in_progress_stories — checks only for in-progress."""

    def test_in_progress(self):
        import sprint_state

        self.assertTrue(sprint_state.has_in_progress_stories(SPRINT_IN_PROGRESS))

    def test_ready_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_in_progress_stories(SPRINT_READY_ONLY))

    def test_mixed_has_in_progress(self):
        import sprint_state

        self.assertTrue(sprint_state.has_in_progress_stories(SPRINT_MIXED_IN_PROGRESS))


class TestReadSprintContent(_HookTestCase):
    """Test read_sprint_content — reads sprint.md from SMM dir."""

    def test_exists(self):
        import sprint_state

        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertEqual(result, SPRINT_READY_ONLY)

    def test_missing(self):
        import sprint_state

        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNone(result)

    def test_symlink(self):
        import sprint_state

        target = self.smm_dir / "real_sprint.md"
        target.write_text(SPRINT_READY_ONLY)
        link = self.smm_dir / "sprint.md"
        link.symlink_to(target)
        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNone(result)


class TestExecutionPlanExists(_HookTestCase):
    """Test execution_plan_exists — checks execution_plan.json in SMM dir."""

    def test_exists(self):
        import sprint_state

        (self.smm_dir / "execution_plan.json").write_text("{}")
        self.assertTrue(sprint_state.execution_plan_exists(self.smm_dir))

    def test_missing(self):
        import sprint_state

        self.assertFalse(sprint_state.execution_plan_exists(self.smm_dir))

    def test_symlink(self):
        import sprint_state

        target = self.smm_dir / "real.json"
        target.write_text("{}")
        link = self.smm_dir / "execution_plan.json"
        link.symlink_to(target)
        self.assertFalse(sprint_state.execution_plan_exists(self.smm_dir))


class TestHasReadyStories(unittest.TestCase):
    """Test has_ready_stories — checks only for ready status."""

    def test_ready_story(self):
        import sprint_state

        self.assertTrue(sprint_state.has_ready_stories(SPRINT_READY_ONLY))

    def test_in_progress_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_ready_stories(SPRINT_IN_PROGRESS))

    def test_done_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_ready_stories(SPRINT_ALL_DONE))

    def test_mixed_no_ready(self):
        import sprint_state

        # SPRINT_MIXED_IN_PROGRESS has done + in-progress, no ready
        self.assertFalse(sprint_state.has_ready_stories(SPRINT_MIXED_IN_PROGRESS))


class TestIsSprintComplete(unittest.TestCase):
    """Test is_sprint_complete — True when no ready or in-progress stories."""

    def test_done_and_deferred_only(self):
        import sprint_state

        self.assertTrue(sprint_state.is_sprint_complete(SPRINT_ALL_DONE))

    def test_ready_not_complete(self):
        import sprint_state

        self.assertFalse(sprint_state.is_sprint_complete(SPRINT_READY_ONLY))

    def test_in_progress_not_complete(self):
        import sprint_state

        self.assertFalse(sprint_state.is_sprint_complete(SPRINT_IN_PROGRESS))

    def test_mixed_not_complete(self):
        import sprint_state

        self.assertFalse(sprint_state.is_sprint_complete(SPRINT_MIXED_IN_PROGRESS))

    def test_empty_string_is_complete(self):
        import sprint_state

        self.assertTrue(sprint_state.is_sprint_complete(""))


if __name__ == "__main__":
    unittest.main()
