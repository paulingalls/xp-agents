#!/usr/bin/env python3
"""Unit tests for commit_handling.is_tdd_red_step: the honest TDD-red
signal that gates the failed-test regression concern in bash_post_tool.

Two independent paths feed the OR: a test-only-dirty working tree (the
red step BEFORE the mandated post-green commit) and a test-only prior
commit (the legacy commit-based signal, preserved). See story-018.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import commit_handling
from conftest import _HookTestCase, make_event
from event_schema import EVENT_TYPE_COMMIT

_CWD = "/repo"


class TestIsTddRedStepWorkingTree(_HookTestCase):
    """Working-tree-based half of the signal: is_tdd_red_step consults
    the CURRENT dirty tree, not just the last commit — the canonical TDD
    red step happens BEFORE the post-green commit exists."""

    def test_test_only_dirty_tree_is_red_step(self):
        with (
            patch("commits.get_uncommitted_files", return_value=["tests/test_x.py"]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            self.assertTrue(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))

    def test_test_files_plus_impl_code_in_flight_is_not_red_step(self):
        """Non-test code also dirty -> a failure may be a real regression."""
        with (
            patch(
                "commits.get_uncommitted_files",
                return_value=["tests/test_x.py", "src/x.py"],
            ),
            patch("commits.get_uncommitted_code_files", return_value=["src/x.py"]),
        ):
            self.assertFalse(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))

    def test_untracked_impl_code_in_flight_is_not_red_step(self):
        """A brand-new, never-``git add``ed production file appears in the
        wide scan but NOT the narrow (staged+unstaged) one. Test-only must
        be judged off the wide scan alone, else this genuine green-phase
        failure is silently suppressed as a deliberate red."""
        with (
            patch(
                "commits.get_uncommitted_files",
                return_value=["tests/test_x.py", "src/new.py"],
            ),
            # narrow helper omits untracked files -> would report "no code"
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            self.assertFalse(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))

    def test_git_timeout_fails_safe(self):
        """get_uncommitted_files -> None (git could not answer) must NOT be
        read as a clean tree — default to "treat failures as regressions"."""
        with (
            patch("commits.get_uncommitted_files", return_value=None),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            self.assertFalse(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))

    def test_no_repo_is_not_red_step(self):
        with (
            patch("commits.get_uncommitted_files", return_value=[]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            self.assertFalse(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))


class TestIsTddRedStepCommitBased(_HookTestCase):
    """Commit-based half of the signal is preserved: a clean tree whose
    last commit was test-only still reads as a red step (commit-first
    TDD workflow, distinct from the mandated red-green-commit path)."""

    def test_clean_tree_prior_test_only_commit_is_still_red_step(self):
        commit = make_event(
            EVENT_TYPE_COMMIT,
            content="test(auth): add failing test for retry path",
            files=["tests/test_auth.py"],
        )
        _common.append_safe(self.smm_dir, commit)

        with (
            patch("commits.get_uncommitted_files", return_value=[]),
            patch("commits.get_uncommitted_code_files", return_value=[]),
        ):
            self.assertTrue(commit_handling.is_tdd_red_step(self.smm_dir, _CWD))


if __name__ == "__main__":
    unittest.main()
