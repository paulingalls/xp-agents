#!/usr/bin/env python3
"""Integration tests for the /xp-sprint-close skill (sprint-032 story-003).

Slice A covers the preload contract; slice B will extend with SKILL.md
text assertions for the dirty-tree refusal, with-gh / without-gh paths,
and merge+cleanup sequencing.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import seed_plan, write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"


class TestSprintClosePreload(_IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    def setUp(self):
        super().setUp()
        # Assert the script exists — no silent skipTest while we're red.
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

    def test_emits_target_branch_via_get_merge_target(self):
        # Stage 2 + recorded plan branch → TARGET_BRANCH = the plan branch.
        write_system_context(self.smm_dir, stage=2)
        seed_plan(self.smm_dir, branch="test/plan-feat")
        subprocess.run(
            ["git", "branch", "test/plan-feat"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "TARGET_BRANCH"), "test/plan-feat"
        )

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
        # _IntegrationTestCase tearDown removes tmpdir, so no manual cleanup.
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "false")

    def test_emits_review_input_path(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        review_input = _extract_preload_var(result.stdout, "REVIEW_INPUT")
        self.assertEqual(review_input, str(self.smm_dir / ".close-review-input.json"))

    def test_exits_zero_with_unwritable_smm(self):
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its six lines (TARGET_BRANCH may be
        # empty when there is no plan) and exit 0.
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                _PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        # All six keys still present.
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
