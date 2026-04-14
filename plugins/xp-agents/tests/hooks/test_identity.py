#!/usr/bin/env python3
"""Tests for identity.py — agent identity resolution utilities.

Covers: resolve_agent_id, is_worktree_teammate, get_current_branch.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
    """is_worktree_teammate detects CLI teammates by cwd path."""

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


class TestGetCurrentBranch(unittest.TestCase):
    """get_current_branch returns branch name or empty string."""

    def test_returns_branch_in_git_repo(self):
        td = tempfile.mkdtemp()
        subprocess.run(["git", "init", td], capture_output=True)
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
