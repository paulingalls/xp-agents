#!/usr/bin/env python3
"""Shared test fixtures for the close-skill family preload tests.

`_ClosePreloadCommonTests` covers the eight assertions every close-skill
preload must satisfy: it emits SMM_DIR, CURRENT_BRANCH, GH_AVAILABLE,
WORKTREE_CLEAN, REVIEW_INPUT (mktemp, unique per call), and exits 0
even with a fresh CLAUDE_PLUGIN_DATA. Subclasses inherit the mixin
plus `_IntegrationTestCase` and supply `_PRELOAD`. The TARGET_BRANCH
assertion is skill-specific (sprint-close uses get-target, plan-close
uses get-primary, free-close will mirror plan-close), so subclasses
own that test individually.
"""

import subprocess
import tempfile
from pathlib import Path

from conftest import _extract_preload_var


class _ClosePreloadCommonTests:
    """Mixin asserting the shared preload contract.

    Subclasses must define:
        _PRELOAD: Path — absolute path to the preload.sh under test.
    """

    _PRELOAD: Path

    def setUp(self) -> None:
        super().setUp()
        # Assert the script exists — no silent skipTest while we're red.
        self.assertTrue(
            self._PRELOAD.is_file(), f"Preload script missing: {self._PRELOAD}"
        )

    def _preload(self) -> subprocess.CompletedProcess:
        return self._run_preload(self._PRELOAD)

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
        # REVIEW_INPUT is a per-invocation tempfile under SMM_DIR — concurrent
        # close skills in different worktrees must not race on a shared path.
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
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its six lines and exit 0.
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                self._PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
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
