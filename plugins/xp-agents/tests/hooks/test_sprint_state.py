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


class TestHasActiveStories(_HookTestCase):
    """Test has_active_stories — delegates to sprint_store."""

    def test_ready_story(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        self.assertTrue(sprint_state.has_active_stories(self.smm_dir))

    def test_in_progress_story(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertTrue(sprint_state.has_active_stories(self.smm_dir))

    def test_done_only(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        self.assertFalse(sprint_state.has_active_stories(self.smm_dir))

    def test_missing_sprint(self):
        import sprint_state

        self.assertFalse(sprint_state.has_active_stories(self.smm_dir))

    def test_mixed_statuses(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED_IN_PROGRESS)
        self.assertTrue(sprint_state.has_active_stories(self.smm_dir))


class TestHasInProgressStories(_HookTestCase):
    """Test has_in_progress_stories — delegates to sprint_store."""

    def test_in_progress(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))

    def test_ready_only(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        self.assertFalse(sprint_state.has_in_progress_stories(self.smm_dir))

    def test_mixed_has_in_progress(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED_IN_PROGRESS)
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))


class TestReadSprintContent(_HookTestCase):
    """Test read_sprint_content — loads sprint.json from SMM dir."""

    def test_exists(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["goal"], "Build auth")

    def test_missing(self):
        import sprint_state

        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNone(result)

    def test_symlink(self):
        import sprint_state

        target = self.smm_dir / "real_sprint.json"
        target.write_text(SPRINT_READY_ONLY)
        link = self.smm_dir / "sprint.json"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            sprint_state.read_sprint_content(self.smm_dir)


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


class TestHasReadyStories(_HookTestCase):
    """Test has_ready_stories — delegates to sprint_store."""

    def test_ready_story(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        self.assertTrue(sprint_state.has_ready_stories(self.smm_dir))

    def test_in_progress_only(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertFalse(sprint_state.has_ready_stories(self.smm_dir))

    def test_done_only(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        self.assertFalse(sprint_state.has_ready_stories(self.smm_dir))

    def test_mixed_no_ready(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED_IN_PROGRESS)
        self.assertFalse(sprint_state.has_ready_stories(self.smm_dir))


class TestIsSprintComplete(_HookTestCase):
    """Test is_sprint_complete — True when no ready/in-progress."""

    def test_done_and_deferred_only(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        self.assertTrue(sprint_state.is_sprint_complete(self.smm_dir))

    def test_ready_not_complete(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        self.assertFalse(sprint_state.is_sprint_complete(self.smm_dir))

    def test_in_progress_not_complete(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertFalse(sprint_state.is_sprint_complete(self.smm_dir))

    def test_mixed_not_complete(self):
        import sprint_state

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED_IN_PROGRESS)
        self.assertFalse(sprint_state.is_sprint_complete(self.smm_dir))

    def test_missing_sprint_is_complete(self):
        import sprint_state

        self.assertTrue(sprint_state.is_sprint_complete(self.smm_dir))


if __name__ == "__main__":
    unittest.main()
