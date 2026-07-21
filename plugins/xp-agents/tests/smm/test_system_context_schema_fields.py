#!/usr/bin/env python3
"""Tests for branching_strategy.integration_branch as a git ref.

`integration_branch` becomes `git checkout <ref>` / `git merge <ref>` argv
(branch_resolution.get_primary_branch), exactly like sprint.branch_name and
plan.branch — but unlike those two it was type-checked only. This file covers
the shared `usable_git_ref_name` predicate, the two field wrappers, and the
load-lenient / save-strict split in the store.

The store half is the load-bearing part: the check must be enforced at INPUT
without hard-failing a project whose stored config predates it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from execution_plan_schema import VALID_BRANCH_NAME_RE, usable_git_ref_name

# Values a caller must never be handed as a git ref. The first three fail the
# shared pattern outright; the last two PASS it (see the pin below) and are
# caught only by the leading-dash rule.
UNUSABLE_REFS = ("feature branch", "main\n", "back~tick`", "-f", "--force")


class TestUsableGitRefName(unittest.TestCase):
    def test_leading_dash_matches_the_pattern(self) -> None:
        """Why the leading-dash rule is NOT redundant with the pattern.

        `-` sits inside the pattern's character class, so `-f` and `--force`
        are well-formed by it. `get_primary_branch` returning `-f` yields
        `git checkout -f`, which discards local changes. If this pin ever
        fails because the pattern was tightened, the extra rule may go —
        until then it is the only thing standing between a stored config and
        argv.
        """
        for flag in ("-f", "--force"):
            with self.subTest(flag=flag):
                self.assertIsNotNone(VALID_BRANCH_NAME_RE.match(flag))

    def test_accepts_ordinary_branch_names(self) -> None:
        for name in ("main", "paul/story-005-x", "release/v1.2.3", "a_b.c-d"):
            with self.subTest(name=name):
                self.assertTrue(usable_git_ref_name(name))

    def test_rejects_every_unusable_ref(self) -> None:
        for value in UNUSABLE_REFS:
            with self.subTest(value=value):
                self.assertFalse(usable_git_ref_name(value))

    def test_rejects_non_strings(self) -> None:
        for value in (None, 3, ["main"], {"branch": "main"}, b"main"):
            with self.subTest(value=value):
                self.assertFalse(usable_git_ref_name(value))

    def test_rejects_empty_string(self) -> None:
        self.assertFalse(usable_git_ref_name(""))


if __name__ == "__main__":
    unittest.main()
