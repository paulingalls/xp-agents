#!/usr/bin/env python3
"""Tests for prepare_review_data.py and the sprint-review preload.

sprint_review_done tests migrated to test_subagent.py::TestSprintReviewerDone
as part of the PostToolUse:Skill replacement plan — the handler now
lives in subagent_stop.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-sprint-review" / "scripts"
    ),
)

from conftest import _HookTestCase, _IntegrationTestCase

# ---------------------------------------------------------------------------
# Sprint fixtures
# ---------------------------------------------------------------------------

SPRINT_MIXED = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** done
- **Dependencies:** none

### story-003: Password reset
- **Size:** M
- **Status:** deferred
- **Dependencies:** story-001

### story-004: OAuth integration
- **Size:** L
- **Status:** ready
- **Dependencies:** story-001
"""

SPRINT_ALL_DONE = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** done
- **Dependencies:** none

### story-003: Password reset
- **Size:** M
- **Status:** done
- **Dependencies:** story-001
"""

SPRINT_ALL_DEFERRED = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15

## Stories

### story-001: User login
- **Size:** M
- **Status:** deferred
- **Dependencies:** none

### story-002: User registration
- **Size:** S
- **Status:** deferred
- **Dependencies:** none
"""

SPRINT_WITH_MILESTONE = """\
# Sprint: Build auth system

- **Sprint ID:** sprint-001
- **Started:** 2026-03-15
- **Milestone:** Milestone 1: Auth Foundation

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
- **Dependencies:** none
"""

SPRINT_NO_ID = """\
# Sprint: Build auth system

## Stories

### story-001: User login
- **Size:** M
- **Status:** done
"""

PRODUCT_SPEC = """\
# Product Spec: Auth System

## Features

### User Registration [planned]
- Users can register with email and password

### JWT Authentication [planned]
- Login returns JWT tokens

### Password Reset [planned]
- Reset password via email link
"""


# ===========================================================================
# prepare_review_data.py
# ===========================================================================


class TestPrepareReviewData(_HookTestCase):
    """M11: prepare_review_data reads sprint + execution_plan, computes velocity."""

    def test_basic_velocity(self):
        """2 done, 1 deferred, 1 ready -> planned=4, delivered=2, carried=1."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 4)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_review_input_structure(self):
        """Output dict has structured keys + paths, not embedded content."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        expected = (
            "sprint_id",
            "goal",
            "velocity",
            "sprint_md_path",
            "execution_plan_md_path",
            "milestone",
        )
        for key in expected:
            self.assertIn(key, result, f"Missing key: {key}")
        # Should NOT have embedded content
        self.assertNotIn("sprint_md", result)
        self.assertNotIn("product_spec_md", result)

    def test_no_sprint_returns_none(self):
        """No sprint.md -> None."""
        import prepare_review_data

        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_all_done_velocity(self):
        """3/3 done -> planned=3, delivered=3, carried=0."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 3)
        self.assertEqual(vel["stories_carried"], 0)

    def test_all_deferred_velocity(self):
        """0/2 delivered, 2/2 carried."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DEFERRED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 2)
        self.assertEqual(vel["stories_delivered"], 0)
        self.assertEqual(vel["stories_carried"], 2)

    def test_atomic_write(self):
        """.sprint-review-input.json exists after run."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        prepare_review_data.run(self.smm_dir)
        self.assertTrue((self.smm_dir / ".sprint-review-input.json").exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_NO_ID)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNone(result)

    def test_sprint_id_in_output(self):
        """sprint_id matches what's in sprint.md."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertEqual(result["sprint_id"], "sprint-001")

    def test_goal_in_output(self):
        """goal matches sprint heading."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertEqual(result["goal"], "Build auth system")

    def test_execution_plan_path_set(self):
        """execution_plan.json exists -> execution_plan_md_path is non-empty."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        (self.smm_dir / "execution_plan.json").write_text("{}")
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        path = result["execution_plan_md_path"]
        self.assertTrue(path)
        self.assertTrue(Path(path).is_file())

    def test_missing_execution_plan_empty_path(self):
        """No execution_plan.json -> execution_plan_md_path=''."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["execution_plan_md_path"], "")

    def test_execution_plan_symlink_empty_path(self):
        """execution_plan.json is symlink -> execution_plan_md_path=''."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        target = self.smm_dir / "_fake_target.json"
        target.write_text("{}")
        (self.smm_dir / "execution_plan.json").symlink_to(target)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["execution_plan_md_path"], "")

    def test_milestone_populated_from_sprint(self):
        """Sprint with Milestone header -> milestone key populated."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_WITH_MILESTONE)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["milestone"], "Milestone 1: Auth Foundation")

    def test_milestone_empty_when_not_in_sprint(self):
        """Sprint without Milestone header -> milestone is ''."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertEqual(result["milestone"], "")

    def test_execution_plan_md_path_key_always_present(self):
        """execution_plan_md_path always present as key in output."""
        import prepare_review_data

        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = prepare_review_data.run(self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("execution_plan_md_path", result)


# ===========================================================================
# sprint_review_done.py
# ===========================================================================


# ===========================================================================
# preload.sh — Integration tests
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-review"
    / "scripts"
    / "preload.sh"
)


class TestSprintReviewPreload(_IntegrationTestCase):
    """M11: preload.sh runs prepare_review_data and outputs paths."""

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_review_input(self):
        """Preload output includes REVIEW_INPUT= line."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        """No sprint.md -> exits 0, no REVIEW_INPUT."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_guide_or_smm(self):
        """Preload is minimal — no guide, no SMM injection."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("XP Values", result.stdout)
        self.assertNotIn("Shared Mental Model", result.stdout)

    def test_preload_creates_review_input_file(self):
        """Preload creates .sprint-review-input.json in SMM dir."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".sprint-review-input.json").exists())


if __name__ == "__main__":
    unittest.main()
