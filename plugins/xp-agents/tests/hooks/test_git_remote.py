#!/usr/bin/env python3
"""Behavior tests for git_remote.has_remote / push_branch."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _branching_fixtures as _bf
import git_remote

_init_repo = _bf.init_repo
_add_bare_remote = _bf.add_bare_remote
_remote_has_branch = _bf.remote_has_branch


class TestHasRemote(unittest.TestCase):
    def test_returns_false_when_no_remote_configured(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertFalse(git_remote.has_remote(td))

    def test_returns_true_when_origin_exists(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            _add_bare_remote(td)
            self.assertTrue(git_remote.has_remote(td))


class TestPushBranch(unittest.TestCase):
    def test_silent_skip_when_no_remote(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertTrue(git_remote.push_branch(td, "main"))

    def test_pushes_to_origin_when_remote_exists(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            _add_bare_remote(td)
            self.assertTrue(git_remote.push_branch(td, "main"))
            self.assertTrue(_remote_has_branch(td, "main"))

    def test_returns_false_when_push_fails(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            _add_bare_remote(td)
            self.assertFalse(git_remote.push_branch(td, "no-such-branch"))


if __name__ == "__main__":
    unittest.main()
