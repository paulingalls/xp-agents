#!/usr/bin/env python3
"""Tests for branching.delete_branch's force-delete fallback."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching


def _checkout_and_merge(td: str, target: str, source: str) -> None:
    subprocess.run(["git", "checkout", target], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", source, "-m", f"merge {source}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_bf.GIT_ENV,
    )


def _setup_merged_branch(td: str, branch: str, *, diverge: bool = False) -> str:
    """Init repo, branch off main with one commit, optionally diverge the
    tracking ref, then merge into main. Returns the main branch name."""
    _bf.init_repo(td)
    if diverge:
        _bf.add_bare_remote(td)
    main = _bf.get_current_branch(td)
    _bf.make_commit(td, branch, f"{branch.replace('/', '-')}.txt", "x", f"add {branch}")
    if diverge:
        _bf.diverge_tracking_ref(td, branch)
    _checkout_and_merge(td, main, branch)
    return main


class TestDeleteBranchBackwardCompatible(unittest.TestCase):
    def test_safe_path_unchanged_when_no_merge_target(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "feature-clean")
            self.assertTrue(branching.delete_branch(td, "feature-clean"))
            self.assertFalse(_bf.branch_exists(td, "feature-clean"))

    def test_returns_false_when_d_refuses_and_no_merge_target(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-001-diverged", diverge=True)
            self.assertFalse(branching.delete_branch(td, "paul/story-001-diverged"))
            self.assertTrue(_bf.branch_exists(td, "paul/story-001-diverged"))


class TestDeleteBranchForceFallback(unittest.TestCase):
    def test_falls_back_to_force_when_merged_to_target(self):
        with tempfile.TemporaryDirectory() as td:
            main = _setup_merged_branch(td, "paul/story-002-merged", diverge=True)
            self.assertTrue(
                branching.delete_branch(td, "paul/story-002-merged", merge_target=main)
            )
            self.assertFalse(_bf.branch_exists(td, "paul/story-002-merged"))


class TestDeleteBranchForceSafety(unittest.TestCase):
    def test_refuses_force_when_not_merged_to_target(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "paul/story-003-unmerged", "u.txt", "x", "add u")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            self.assertFalse(
                branching.delete_branch(
                    td, "paul/story-003-unmerged", merge_target=main
                )
            )
            self.assertTrue(_bf.branch_exists(td, "paul/story-003-unmerged"))


class TestDeleteBranchMissing(unittest.TestCase):
    def test_returns_false_when_branch_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            self.assertFalse(
                branching.delete_branch(td, "no-such-branch", merge_target=main)
            )


if __name__ == "__main__":
    unittest.main()
