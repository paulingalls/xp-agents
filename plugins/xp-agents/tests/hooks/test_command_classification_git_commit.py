#!/usr/bin/env python3
"""Tests for command classification: git-commit detection.

Pure parsing tests — no SMM state needed. Split from test_bash_parsing.py
(story-008) when that file crossed the 500-line cap, then split again from
test_command_classification.py (was 510 lines) when IT crossed the cap.
Test-runner detection lives in test_command_classification_test_runner.py.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits
import git_commits


class TestIsGitCommit(unittest.TestCase):
    def test_git_commit_m(self):
        self.assertTrue(git_commits.is_git_commit("git commit -m 'msg'"))

    def test_git_commit_am(self):
        self.assertTrue(git_commits.is_git_commit("git commit -am 'msg'"))

    def test_git_commit_with_path(self):
        self.assertTrue(git_commits.is_git_commit("cd /tmp && git commit -m 'x'"))

    def test_not_git_status(self):
        self.assertFalse(git_commits.is_git_commit("git status"))

    def test_not_ls(self):
        self.assertFalse(git_commits.is_git_commit("ls -la"))

    def test_git_commit_no_message(self):
        self.assertTrue(git_commits.is_git_commit("git commit"))

    def test_not_in_double_quotes(self):
        self.assertFalse(
            git_commits.is_git_commit('append.sh --content "before git commit"')
        )

    def test_not_in_single_quotes(self):
        self.assertFalse(git_commits.is_git_commit("echo 'git commit is great'"))

    def test_not_in_heredoc(self):
        cmd = "cat <<'SMMEOF' | python3 x.py\nbefore git commit\nSMMEOF"
        self.assertFalse(git_commits.is_git_commit(cmd))

    def test_git_dash_C_path_commit(self):
        # Agents use `git -C <abs-path>` to avoid cd-poisoning Stop hooks
        # (per feedback). The detector must recognize this form or the
        # pre-/post-tool hooks both go silent — root cause of bug
        # ec4c804139e4 + 731915a2d4d2.
        self.assertTrue(
            git_commits.is_git_commit(
                "git -C /Users/paulingalls/src/projects/xp-agents commit -m 'x'"
            )
        )

    def test_git_dash_C_in_chained_command(self):
        # Real production shape: stage with -C then commit with -C.
        cmd = "git -C /repo add scripts/x.py && git -C /repo commit -m 'msg'"
        self.assertTrue(git_commits.is_git_commit(cmd))

    def test_git_dash_C_with_heredoc_message(self):
        # The most common production shape from sprint-052's free session.
        cmd = (
            "git -C /repo commit -m \"$(cat <<'EOF'\n"
            "subject line\n"
            "\nResolves-Event: deadbeef0001\n"
            'EOF\n)"'
        )
        self.assertTrue(git_commits.is_git_commit(cmd))

    def test_git_dash_C_status_not_commit(self):
        # Negative: `-C <path>` with a non-commit subcommand must stay False.
        self.assertFalse(git_commits.is_git_commit("git -C /repo status"))

    def test_git_merge_matches(self):
        # Merge commits also produce commits — must be tracked. Confirmed
        # silent gap: 425f1c2 (real merge on this branch) was absent from
        # events.jsonl pre-fix.
        self.assertTrue(git_commits.is_git_commit("git merge --no-ff feature"))

    def test_git_dash_C_merge_matches(self):
        self.assertTrue(git_commits.is_git_commit("git -C /repo merge --no-ff feature"))

    def test_commit_tree_plumbing_rejected(self):
        # Plumbing commands must not false-positive. The `(?!-)` lookahead
        # rejects `commit-tree` after the `\b` matches between `t` and `-`.
        self.assertFalse(git_commits.is_git_commit("git commit-tree -p HEAD"))

    def test_merge_tree_plumbing_rejected(self):
        self.assertFalse(git_commits.is_git_commit("git merge-tree A B"))

    def test_git_dash_c_config_override_commit(self):
        # `-c <name>=<value>` config override must not bypass detection.
        self.assertTrue(
            git_commits.is_git_commit("git -c user.email=x@y commit -m 'msg'")
        )

    def test_git_git_dir_long_option_commit(self):
        self.assertTrue(git_commits.is_git_commit("git --git-dir=/p/.git commit"))

    def test_git_work_tree_long_option_commit(self):
        self.assertTrue(git_commits.is_git_commit("git --work-tree=/p commit"))

    def test_git_paginate_short_flag_commit(self):
        self.assertTrue(git_commits.is_git_commit("git -p commit -m 'x'"))


class TestStripQuotedPublic(unittest.TestCase):
    """story-007: `_strip_quoted` was promoted to public `strip_quoted` so
    callers (commits.parse_effective_cwd, bash_post_tool) can share one
    pre-stripped scan target with `is_git_commit` instead of each
    re-stripping the command independently."""

    def test_public_name_exists(self):
        """`strip_quoted` is the supported public name."""
        self.assertTrue(callable(getattr(git_commits, "strip_quoted", None)))

    def test_strips_single_quotes(self):
        self.assertNotIn("git commit", git_commits.strip_quoted("echo 'git commit'"))

    def test_strips_double_quotes(self):
        self.assertNotIn("git commit", git_commits.strip_quoted('echo "git commit"'))

    def test_strips_heredoc(self):
        cmd = "cat <<'EOF'\ngit commit body\nEOF"
        self.assertNotIn("git commit", git_commits.strip_quoted(cmd))


class TestIsGitCommitScanTarget(unittest.TestCase):
    """story-007: `is_git_commit` accepts an optional pre-stripped
    scan_target so callers that already have one (bash_post_tool runs
    strip_quoted once per Bash and threads it through) avoid the
    double-strip cost."""

    def test_default_strips_internally(self):
        """Omitting scan_target keeps the original behavior — quoted
        `git commit` inside an arg must NOT match."""
        self.assertFalse(
            git_commits.is_git_commit('append.sh --content "before git commit"')
        )

    def test_pre_stripped_scan_target_honored(self):
        """A pre-stripped scan_target is consulted directly; the quoted
        text in the original command is irrelevant since the caller
        already removed it."""
        cmd = "git commit -m 'see git push'"
        scan_target = git_commits.strip_quoted(cmd)
        self.assertTrue(git_commits.is_git_commit(cmd, scan_target=scan_target))

    def test_pre_stripped_scan_target_takes_precedence(self):
        """When scan_target is provided, it's the SCAN; the function
        does not re-strip command. Pass a deliberately neutered
        scan_target to prove the function trusts the caller."""
        cmd = "git commit -m 'msg'"  # would match by default
        # Caller passes an empty scan_target — function honors it, returns False.
        self.assertFalse(git_commits.is_git_commit(cmd, scan_target=""))


class TestGitPrefixSharedRegex(unittest.TestCase):
    """git_commits.GIT_PREFIX is reused by commits.get_code_files_for_review
    for `git add` / `git commit -a` detection. Same root-cause class as
    is_git_commit: agents using `git -C <path> add` must not silently
    bypass the unstaged-tracked-files enrichment."""

    def test_git_dash_C_add_matches(self):
        pattern = git_commits.GIT_PREFIX + r"add\b"
        self.assertTrue(re.search(pattern, "git -C /repo add scripts/x.py"))

    def test_git_add_bare_still_matches(self):
        pattern = git_commits.GIT_PREFIX + r"add\b"
        self.assertTrue(re.search(pattern, "git add scripts/x.py"))

    def test_git_dash_C_commit_dash_a_matches(self):
        pattern = git_commits.GIT_PREFIX + r"commit\s+-a"
        self.assertTrue(re.search(pattern, "git -C /repo commit -am 'msg'"))

    def test_git_status_does_not_match_add(self):
        pattern = git_commits.GIT_PREFIX + r"add\b"
        self.assertFalse(re.search(pattern, "git -C /repo status"))


class TestParseCommitMessage(unittest.TestCase):
    def test_standard_output(self):
        response = "[main abc123] Add auth module\n 3 files changed, 45 insertions(+)"
        result = commits.parse_commit_message(response)
        self.assertEqual(result, "Add auth module")

    def test_no_match(self):
        result = commits.parse_commit_message("error: something went wrong")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
