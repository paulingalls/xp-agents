#!/usr/bin/env python3
"""Tests for prepare_review_data.py and the sprint-review preload.

sprint_review_done tests migrated to test_subagent.py::TestSprintReviewerDone
as part of the PostToolUse:Skill replacement plan — the handler now
lives in subagent_stop.py.
"""

import sys
import unittest
import unittest.mock
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

import marker_names
from conftest import (
    _HookTestCase,
    _IntegrationTestCase,
    _s,
    _sprint_json,
)

_SRI = marker_names.SPRINT_REVIEW_INPUT_PREFIX

# ---------------------------------------------------------------------------
# Sprint fixtures
# ---------------------------------------------------------------------------

SPRINT_MIXED = _sprint_json(
    [
        _s("story-001", "User login", "done"),
        _s("story-002", "User registration", "done"),
        _s("story-003", "Password reset", "deferred", dependencies=["story-001"]),
        _s("story-004", "OAuth integration", "ready", dependencies=["story-001"]),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_ALL_DONE = _sprint_json(
    [
        _s("story-001", "User login", "done"),
        _s("story-002", "User registration", "done"),
        _s("story-003", "Password reset", "done", dependencies=["story-001"]),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_ALL_DEFERRED = _sprint_json(
    [
        _s("story-001", "User login", "deferred"),
        _s("story-002", "User registration", "deferred"),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)

SPRINT_WITH_MILESTONE = _sprint_json(
    [_s("story-001", "User login", "done")],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
    milestone="Milestone 1: Auth Foundation",
)

SPRINT_NO_ID = _sprint_json(
    [_s("story-001", "User login", "done")],
    goal="Build auth system",
)

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

    def _run_with(self, sprint_text: str) -> dict:
        """Write sprint.json, run prepare_review_data, return non-None result.

        Centralizes the Optional-narrowing assert that pyright basic mode
        requires after Optional-returning calls — negative tests
        (test_no_sprint_returns_none, test_malformed_sprint_returns_none,
        test_atomic_write_uses_target_path) opt out and call directly.
        """
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(sprint_text)
        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        assert result is not None
        return result

    def test_basic_velocity(self):
        """2 done, 1 deferred, 1 ready -> planned=4, delivered=2, carried=1."""
        result = self._run_with(SPRINT_MIXED)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 4)
        self.assertEqual(vel["stories_delivered"], 2)
        self.assertEqual(vel["stories_carried"], 1)

    def test_review_input_structure(self):
        """Output dict has structured keys + paths, not embedded content."""
        result = self._run_with(SPRINT_MIXED)
        expected = (
            "sprint_id",
            "goal",
            "velocity",
            "sprint_path",
            "execution_plan_path",
            "milestone",
        )
        for key in expected:
            self.assertIn(key, result, f"Missing key: {key}")
        # Should NOT have embedded content
        self.assertNotIn("sprint_md", result)
        self.assertNotIn("product_spec_md", result)
        # Should NOT carry the old .md-suffixed key names
        self.assertNotIn("sprint_md_path", result)
        self.assertNotIn("execution_plan_md_path", result)

    def test_no_sprint_returns_none(self):
        """No sprint.json -> None."""
        import prepare_review_data

        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        self.assertIsNone(result)

    def test_all_done_velocity(self):
        """3/3 done -> planned=3, delivered=3, carried=0."""
        result = self._run_with(SPRINT_ALL_DONE)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 3)
        self.assertEqual(vel["stories_delivered"], 3)
        self.assertEqual(vel["stories_carried"], 0)

    def test_all_deferred_velocity(self):
        """0/2 delivered, 2/2 carried."""
        result = self._run_with(SPRINT_ALL_DEFERRED)
        vel = result["velocity"]
        self.assertEqual(vel["stories_planned"], 2)
        self.assertEqual(vel["stories_delivered"], 0)
        self.assertEqual(vel["stories_carried"], 2)

    def test_atomic_write_uses_target_path(self):
        """run() writes to the provided target path, not a fixed name."""
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        target = self.smm_dir / f"{_SRI}test-XYZ123"
        prepare_review_data.run(self.smm_dir, target)
        self.assertTrue(target.exists())

    def test_malformed_sprint_returns_none(self):
        """Sprint without sprint_id -> None."""
        import prepare_review_data

        (self.smm_dir / "sprint.json").write_text(SPRINT_NO_ID)
        result = prepare_review_data.run(self.smm_dir, self.smm_dir / f"{_SRI}json")
        self.assertIsNone(result)

    def test_sprint_id_in_output(self):
        """sprint_id matches what's in sprint.json."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["sprint_id"], "sprint-001")

    def test_goal_in_output(self):
        """goal matches sprint heading."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["goal"], "Build auth system")

    def test_execution_plan_path_set(self):
        """execution_plan.json exists -> execution_plan_path is non-empty."""
        (self.smm_dir / "execution_plan.json").write_text("{}")
        result = self._run_with(SPRINT_MIXED)
        path = result["execution_plan_path"]
        self.assertTrue(path)
        self.assertTrue(Path(path).is_file())

    def test_missing_execution_plan_empty_path(self):
        """No execution_plan.json -> execution_plan_path=''."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["execution_plan_path"], "")

    def test_execution_plan_symlink_empty_path(self):
        """execution_plan.json is symlink -> execution_plan_path=''."""
        target = self.smm_dir / "_fake_target.json"
        target.write_text("{}")
        (self.smm_dir / "execution_plan.json").symlink_to(target)
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["execution_plan_path"], "")

    def test_unreadable_execution_plan_degrades_instead_of_raising(self):
        """EACCES from the plan probe -> execution_plan_path='', no traceback.

        `Path.exists`/`Path.is_symlink` — what `plan_exists` is built on —
        propagate EACCES on every interpreter before 3.14, whose ignore list is
        only ENOENT/ENOTDIR/EBADF/ELOOP. One sudo'd run leaving the SMM dir
        root-owned reaches this. Patched rather than chmod'd so the test proves
        the guard on an interpreter (3.14+) whose stdlib would swallow it
        anyway — the reason the missing guard survived a green suite.
        """
        import prepare_review_data

        with unittest.mock.patch.object(
            prepare_review_data.execution_plan_store,
            "plan_exists",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["execution_plan_path"], "")

    def test_milestone_populated_from_sprint(self):
        """Sprint with Milestone header -> milestone key populated."""
        result = self._run_with(SPRINT_WITH_MILESTONE)
        self.assertEqual(result["milestone"], "Milestone 1: Auth Foundation")

    def test_milestone_empty_when_not_in_sprint(self):
        """Sprint without Milestone header -> milestone is ''."""
        result = self._run_with(SPRINT_MIXED)
        self.assertEqual(result["milestone"], "")

    def test_execution_plan_path_key_always_present(self):
        """execution_plan_path always present as key in output."""
        result = self._run_with(SPRINT_MIXED)
        self.assertIn("execution_plan_path", result)


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
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_review_input(self):
        """Preload output includes REVIEW_INPUT= line."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_sprint_graceful(self):
        """No sprint.json -> exits 0, no REVIEW_INPUT."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("REVIEW_INPUT=", result.stdout)

    def test_preload_no_guide_or_smm(self):
        """Preload is minimal — no guide, no SMM injection."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Extreme Programming", result.stdout)
        self.assertNotIn("Shared Mental Model", result.stdout)

    def test_preload_creates_review_input_file_via_mktemp(self):
        """Preload creates a per-invocation .sprint-review-input.XXXXXX tempfile."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        candidates = list(self.smm_dir.glob(f"{_SRI}*"))
        self.assertEqual(len(candidates), 1, candidates)
        self.assertNotEqual(candidates[0].name, f"{_SRI}json")

    def test_preload_review_input_path_is_unique_per_call(self):
        """Two preload calls produce distinct REVIEW_INPUT paths."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        first = self._run_preload(_PRELOAD_SCRIPT).stdout
        second = self._run_preload(_PRELOAD_SCRIPT).stdout
        # Each REVIEW_INPUT line carries the absolute path; extract the path.
        first_path = first.split("REVIEW_INPUT=", 1)[1].split("\n", 1)[0].strip()
        second_path = second.split("REVIEW_INPUT=", 1)[1].split("\n", 1)[0].strip()
        self.assertNotEqual(first_path, second_path)

    def test_preload_no_sprint_does_not_leave_stale_tempfile(self):
        """When prep returns no data, the mktemp file is removed."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.smm_dir.glob(f"{_SRI}*")), [])


if __name__ == "__main__":
    unittest.main()
