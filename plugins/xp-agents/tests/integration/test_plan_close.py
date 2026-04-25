#!/usr/bin/env python3
"""Integration tests for the /xp-plan-close skill (sprint-033 story-001).

Mirrors test_sprint_close.py — six preload fields, but TARGET_BRANCH
resolves to the primary integration branch (plan-close merges plan
into primary, not into another plan).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"


class TestPlanClosePreload(_IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    def setUp(self):
        super().setUp()
        self.assertTrue(_PRELOAD.is_file(), f"Preload script missing: {_PRELOAD}")

    def _preload(self) -> subprocess.CompletedProcess:
        return self._run_preload(_PRELOAD)

    def test_emits_smm_dir(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SMM_DIR"), str(self.smm_dir)
        )

    def test_emits_current_branch(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        actual_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"), actual_branch
        )

    def test_emits_target_branch_as_primary(self):
        # Plan-close always merges plan branch into primary — not into the
        # plan branch itself. Use get-primary, NOT get-target (which would
        # return the plan branch when called from the plan branch).
        write_system_context(self.smm_dir, stage=2)
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        # check=True so a broken branching.py doesn't yield "" == "" false-green.
        primary = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "get-primary",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(primary, "", "branching.py get-primary must resolve")
        self.assertEqual(_extract_preload_var(result.stdout, "TARGET_BRANCH"), primary)

    def test_emits_gh_available_boolean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        gh = _extract_preload_var(result.stdout, "GH_AVAILABLE")
        self.assertIn(gh, ("true", "false"))

    def test_emits_worktree_clean_true_on_clean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "true")

    def test_emits_worktree_clean_false_when_dirty(self):
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "false")

    def test_emits_review_input_path(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        review_input = _extract_preload_var(result.stdout, "REVIEW_INPUT")
        self.assertIsNotNone(review_input)
        review_path = Path(review_input)
        self.assertEqual(review_path.parent, self.smm_dir)
        self.assertTrue(review_path.name.startswith(".close-review-input."))
        self.assertTrue(review_path.exists(), "mktemp should create the file")

    def test_review_input_path_is_unique_per_call(self):
        first = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        second = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        self.assertNotEqual(first, second)

    def test_exits_zero_with_unwritable_smm(self):
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                _PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in (
            "SMM_DIR",
            "CURRENT_BRANCH",
            "TARGET_BRANCH",
            "GH_AVAILABLE",
            "WORKTREE_CLEAN",
            "REVIEW_INPUT",
        ):
            self.assertIsNotNone(
                _extract_preload_var(result.stdout, key),
                f"Missing key in preload output: {key}",
            )


if __name__ == "__main__":
    unittest.main()
