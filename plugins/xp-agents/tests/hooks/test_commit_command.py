#!/usr/bin/env python3
"""Direct-import tests for scripts/commit_command.py.

Exhaustive coverage of these behaviors already lives in test_commits.py,
which reaches them through commits.py's re-export. These tests pin that
commit_command is independently importable and behaves correctly when
imported directly, not merely through the re-export.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_command


class TestCommitCommandDirectImport(unittest.TestCase):
    def test_parse_effective_cwd_git_dash_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = commit_command.parse_effective_cwd(
                f"git -C {tmp} commit -m 'msg'", "/fallback"
            )
            self.assertEqual(result, tmp)

    def test_parse_effective_cwd_no_match_returns_fallback(self):
        result = commit_command.parse_effective_cwd("git status", "/fallback")
        self.assertEqual(result, "/fallback")

    def test_dash_c_unreachable_true_for_variable(self):
        self.assertTrue(commit_command.dash_c_unreachable('git -C "$WT" commit'))

    def test_dash_c_unreachable_false_for_literal_path(self):
        self.assertFalse(commit_command.dash_c_unreachable("git -C /tmp/repo commit"))

    def test_is_escape_hatch_commit_true(self):
        self.assertTrue(
            commit_command.is_escape_hatch_commit('git commit -m "[chore] tidy up"')
        )

    def test_is_escape_hatch_commit_false(self):
        self.assertFalse(
            commit_command.is_escape_hatch_commit('git commit -m "WIP fix"')
        )

    def test_extract_commit_message_simple(self):
        self.assertEqual(
            commit_command.extract_commit_message('git commit -m "hello world"'),
            "hello world",
        )

    def test_extract_commit_message_none(self):
        self.assertIsNone(commit_command.extract_commit_message("git status"))


if __name__ == "__main__":
    unittest.main()
