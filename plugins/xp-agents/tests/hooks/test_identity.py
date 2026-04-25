#!/usr/bin/env python3
"""Tests for identity.py — agent identity resolution utilities.

Covers: resolve_agent_id, is_worktree_teammate, get_current_branch, user_namespace.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import identity


class TestResolveAgentId(unittest.TestCase):
    def test_platform_provided_agent_id(self):
        result = identity.resolve_agent_id({"agent_id": "xp-teammate-001"})
        self.assertEqual(result, "xp-teammate-001")

    def test_worktree_cwd_extracts_name(self):
        result = identity.resolve_agent_id(
            {"cwd": "/home/user/project/.claude/worktrees/teammate-story-001"}
        )
        self.assertEqual(result, "teammate-story-001")

    def test_nested_worktree_cwd(self):
        result = identity.resolve_agent_id(
            {"cwd": "/home/user/project/.claude/worktrees/teammate-story-001/src/lib"}
        )
        self.assertEqual(result, "teammate-story-001")

    def test_non_worktree_cwd_returns_main(self):
        result = identity.resolve_agent_id({"cwd": "/home/user/project/src"})
        self.assertEqual(result, "main")

    def test_no_cwd_returns_main(self):
        result = identity.resolve_agent_id({})
        self.assertEqual(result, "main")

    def test_empty_agent_id_falls_through_to_cwd(self):
        result = identity.resolve_agent_id(
            {"agent_id": "", "cwd": "/x/.claude/worktrees/teammate-story-002"}
        )
        self.assertEqual(result, "teammate-story-002")

    def test_platform_agent_id_takes_precedence_over_worktree_cwd(self):
        inp = {
            "agent_id": "subagent-abc",
            "cwd": "/x/.claude/worktrees/teammate-story-001",
        }
        result = identity.resolve_agent_id(inp)
        self.assertEqual(result, "subagent-abc")


class TestIsWorktreeTeammate(unittest.TestCase):
    """is_worktree_teammate detects CLI teammates by cwd path or env var."""

    def test_teammate_cwd_detected(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/teammate-story-001/src"}
        self.assertTrue(identity.is_worktree_teammate(inp))

    def test_teammate_cwd_root(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/teammate-story-002"}
        self.assertTrue(identity.is_worktree_teammate(inp))

    def test_non_teammate_worktree_not_detected(self):
        inp = {"cwd": "/home/user/project/.claude/worktrees/explore-abc/src"}
        self.assertFalse(identity.is_worktree_teammate(inp))

    def test_regular_cwd_not_detected(self):
        inp = {"cwd": "/home/user/project/src"}
        self.assertFalse(identity.is_worktree_teammate(inp))

    def test_empty_cwd_not_detected(self):
        self.assertFalse(identity.is_worktree_teammate({"cwd": ""}))

    def test_no_cwd_field_not_detected(self):
        self.assertFalse(identity.is_worktree_teammate({}))

    def test_env_var_fallback_when_cwd_fails(self):
        """XP_TEAMMATE_NAME env var detected when cwd has no worktree path."""
        inp = {"cwd": "/home/user/project/src"}
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "teammate-step-1"}):
            self.assertTrue(identity.is_worktree_teammate(inp))

    def test_env_var_without_teammate_prefix_not_detected(self):
        """XP_TEAMMATE_NAME without teammate- prefix is not detected."""
        inp = {"cwd": "/home/user/project/src"}
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "explorer-1"}):
            self.assertFalse(identity.is_worktree_teammate(inp))

    def test_cwd_takes_precedence_over_env_var(self):
        """CWD detection still works even when env var is set."""
        inp = {"cwd": "/home/user/project/.claude/worktrees/teammate-story-001"}
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "teammate-step-2"}):
            self.assertTrue(identity.is_worktree_teammate(inp))


class TestUserNamespace(unittest.TestCase):
    """user_namespace extracts a slug from git config for branch naming."""

    def test_email_local_part_slug(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="paul@paulingalls.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_email_with_dots_and_plus(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="first.last+tag@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "first-last-tag")

    def test_uppercase_lowered(self):
        with patch("identity.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="PAUL@example.com\n"
            )
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul")

    def test_name_fallback(self):
        email_result = subprocess.CompletedProcess([], 1, stdout="")
        name_result = subprocess.CompletedProcess([], 0, stdout="Paul Ingalls\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "paul-ingalls")

    def test_both_unset_returns_default(self):
        fail = subprocess.CompletedProcess([], 1, stdout="")
        with patch("identity.subprocess.run", return_value=fail):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_email_without_at_falls_to_name(self):
        """Email without @ is ignored, falls back to user.name."""
        email_result = subprocess.CompletedProcess([], 0, stdout="localonly\n")
        name_result = subprocess.CompletedProcess([], 0, stdout="Fallback Name\n")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return name_result

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "fallback-name")

    def test_slugify_all_special_chars_falls_to_default(self):
        """Email local-part that slugifies to empty falls through."""
        email_result = subprocess.CompletedProcess([], 0, stdout="---@example.com\n")
        fail = subprocess.CompletedProcess([], 1, stdout="")

        def side_effect(cmd, **kwargs):
            if "user.email" in cmd:
                return email_result
            return fail

        with patch("identity.subprocess.run", side_effect=side_effect):
            result = identity.user_namespace("/tmp")
            self.assertEqual(result, "user")

    def test_real_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main", td], capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            result = identity.user_namespace(td)
            self.assertEqual(result, "test")


class TestGetCurrentBranch(unittest.TestCase):
    """get_current_branch returns branch name or empty string."""

    def test_returns_branch_in_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-b", "main", td], capture_output=True)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "init"],
                cwd=td,
                capture_output=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "t",
                    "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t",
                },
            )
            result = identity.get_current_branch(td)
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_returns_empty_on_invalid_dir(self):
        result = identity.get_current_branch("/nonexistent/path")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
