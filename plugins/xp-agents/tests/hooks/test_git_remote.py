#!/usr/bin/env python3
"""Behavior tests for git_remote.has_remote / push_branch."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _branching_fixtures as _bf
import git_remote

_init_repo = _bf.init_repo


def _make_bare_remote(parent: str, name: str = "origin") -> str:
    bare = str(Path(parent) / f"{name}.bare")
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", bare], capture_output=True, check=True
    )
    return bare


def _add_remote(repo: str, bare: str, name: str = "origin") -> None:
    subprocess.run(
        ["git", "remote", "add", name, bare], cwd=repo, capture_output=True, check=True
    )


class TestHasRemote(unittest.TestCase):
    def test_returns_false_when_no_remote_configured(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertFalse(git_remote.has_remote(td))

    def test_returns_true_when_origin_exists(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            bare_parent = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, bare_parent, ignore_errors=True)
            bare = _make_bare_remote(bare_parent)
            _add_remote(td, bare)
            self.assertTrue(git_remote.has_remote(td))


class TestPushBranch(unittest.TestCase):
    def test_silent_skip_when_no_remote(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertTrue(git_remote.push_branch(td, "main"))

    def test_pushes_to_origin_when_remote_exists(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            bare_parent = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, bare_parent, ignore_errors=True)
            bare = _make_bare_remote(bare_parent)
            _add_remote(td, bare)
            self.assertTrue(git_remote.push_branch(td, "main"))
            r = subprocess.run(
                ["git", "branch"], cwd=bare, capture_output=True, text=True, check=True
            )
            self.assertIn("main", r.stdout)

    def test_returns_false_when_push_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            bare_parent = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, bare_parent, ignore_errors=True)
            bare = _make_bare_remote(bare_parent)
            _add_remote(td, bare)
            # Pushing a branch that doesn't exist locally must fail loud
            # so callers can surface it instead of pretending success.
            self.assertFalse(git_remote.push_branch(td, "no-such-branch"))


if __name__ == "__main__":
    unittest.main()
