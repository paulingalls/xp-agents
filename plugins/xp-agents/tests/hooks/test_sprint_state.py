#!/usr/bin/env python3
"""Tests for sprint_state.py: sprint/product_spec state detection helpers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase

SPRINT_READY = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** ready
- **Dependencies:** none
"""

SPRINT_IN_PROGRESS = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** in-progress
- **Dependencies:** none
"""

SPRINT_DONE_ONLY = """\
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
- **Status:** deferred
- **Dependencies:** none
"""

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
- **Status:** in-progress
- **Dependencies:** none
"""


class TestHasActiveStories(unittest.TestCase):
    """Test has_active_stories — checks for ready or in-progress."""

    def test_ready_story(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_READY))

    def test_in_progress_story(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_IN_PROGRESS))

    def test_done_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_active_stories(SPRINT_DONE_ONLY))

    def test_empty_string(self):
        import sprint_state

        self.assertFalse(sprint_state.has_active_stories(""))

    def test_mixed_statuses(self):
        import sprint_state

        self.assertTrue(sprint_state.has_active_stories(SPRINT_MIXED))


class TestHasInProgressStories(unittest.TestCase):
    """Test has_in_progress_stories — checks only for in-progress."""

    def test_in_progress(self):
        import sprint_state

        self.assertTrue(sprint_state.has_in_progress_stories(SPRINT_IN_PROGRESS))

    def test_ready_only(self):
        import sprint_state

        self.assertFalse(sprint_state.has_in_progress_stories(SPRINT_READY))

    def test_mixed_has_in_progress(self):
        import sprint_state

        self.assertTrue(sprint_state.has_in_progress_stories(SPRINT_MIXED))


class TestReadSprintContent(_HookTestCase):
    """Test read_sprint_content — reads sprint.md from SMM dir."""

    def test_exists(self):
        import sprint_state

        (self.smm_dir / "sprint.md").write_text(SPRINT_READY)
        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertEqual(result, SPRINT_READY)

    def test_missing(self):
        import sprint_state

        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNone(result)

    def test_symlink(self):
        import sprint_state

        target = self.smm_dir / "real_sprint.md"
        target.write_text(SPRINT_READY)
        link = self.smm_dir / "sprint.md"
        link.symlink_to(target)
        result = sprint_state.read_sprint_content(self.smm_dir)
        self.assertIsNone(result)


class TestProductSpecExists(_HookTestCase):
    """Test product_spec_exists — checks product_spec.md in SMM dir."""

    def test_exists(self):
        import sprint_state

        (self.smm_dir / "product_spec.md").write_text("# Product Spec\n")
        self.assertTrue(sprint_state.product_spec_exists(self.smm_dir))

    def test_missing(self):
        import sprint_state

        self.assertFalse(sprint_state.product_spec_exists(self.smm_dir))

    def test_symlink(self):
        import sprint_state

        target = self.smm_dir / "real_spec.md"
        target.write_text("# Product Spec\n")
        link = self.smm_dir / "product_spec.md"
        link.symlink_to(target)
        self.assertFalse(sprint_state.product_spec_exists(self.smm_dir))


if __name__ == "__main__":
    unittest.main()
