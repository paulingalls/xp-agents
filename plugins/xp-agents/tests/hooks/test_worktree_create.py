#!/usr/bin/env python3
"""Tests for WorktreeCreate hook: branch base customization.

Platform input: {session_id, transcript_path, cwd, hook_event_name, name}.
The hook generates worktree path under .claude/worktrees/<name> in repo root,
creates a branch worktree-<name> from the current branch (not origin/HEAD).
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import worktree

# Real platform input format
_INPUT = {
    "session_id": "test",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/repo",
    "hook_event_name": "WorktreeCreate",
    "name": "abc123",
}


class TestWorktreeCreate(unittest.TestCase):
    """WorktreeCreate hook creates worktree from current branch."""

    def setUp(self):
        import importlib

        import worktree_create

        importlib.reload(worktree_create)
        self.worktree_create = worktree_create

    def _run_hook(
        self,
        current: str,
        default: str,
        input_data=None,
    ) -> tuple[str, mock.MagicMock]:
        """Run hook with mocked branch detection. Returns (result, mock_run)."""
        data = input_data or _INPUT
        with (
            mock.patch.object(
                _common,
                "get_current_branch",
                return_value=current,
            ),
            mock.patch.object(
                self.worktree_create,
                "_get_default_branch",
                return_value=default,
            ),
            mock.patch.object(
                worktree,
                "resolve_git_root",
                return_value="/repo",
            ),
            mock.patch("subprocess.run") as mock_run,
            mock.patch("pathlib.Path.mkdir"),
        ):
            result = self.worktree_create.run(data)
            return result, mock_run

    def test_creates_from_current_branch_when_not_default(self):
        """On feature/v2 with default=main, worktree branches from it."""
        result, mock_run = self._run_hook("feature/v2", "main")
        self.assertIn("abc123", result)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[-1], "feature/v2")

    def test_creates_without_base_when_on_default(self):
        """On main with default=main, no base ref appended."""
        _, mock_run = self._run_hook("main", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            [
                "git",
                "worktree",
                "add",
                "-b",
                "worktree-abc123",
                "/repo/.claude/worktrees/abc123",
            ],
        )

    def test_handles_missing_remote_gracefully(self):
        """No origin/HEAD → empty default, no base ref appended."""
        _, mock_run = self._run_hook("feature/v2", "")
        cmd = mock_run.call_args[0][0]
        # Should NOT append feature/v2 — can't compare without default
        self.assertNotIn("feature/v2", cmd)

    def test_handles_detached_head(self):
        """Detached HEAD → empty current, no base ref appended."""
        _, mock_run = self._run_hook("", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            [
                "git",
                "worktree",
                "add",
                "-b",
                "worktree-abc123",
                "/repo/.claude/worktrees/abc123",
            ],
        )

    def test_returns_worktree_path(self):
        """run() returns the worktree path."""
        result, _ = self._run_hook("main", "main")
        self.assertEqual(result, "/repo/.claude/worktrees/abc123")

    def test_branch_name_includes_worktree_prefix(self):
        """Branch is named worktree-<name>."""
        _, mock_run = self._run_hook("main", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[4], "worktree-abc123")

    def test_fails_when_git_worktree_add_fails(self):
        """CalledProcessError propagates when git worktree add fails."""
        with (
            mock.patch.object(
                _common,
                "get_current_branch",
                return_value="v2",
            ),
            mock.patch.object(
                self.worktree_create,
                "_get_default_branch",
                return_value="main",
            ),
            mock.patch.object(
                worktree,
                "resolve_git_root",
                return_value="/repo",
            ),
            mock.patch("pathlib.Path.mkdir"),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.worktree_create.run(_INPUT)

    def test_git_stdout_suppressed(self):
        """git worktree add stdout is DEVNULL."""
        _, mock_run = self._run_hook("v2", "main")
        kwargs = mock_run.call_args[1]
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_generates_name_when_missing(self):
        """Missing name field generates a uuid-based name."""
        data = {
            "session_id": "t",
            "cwd": "/repo",
            "hook_event_name": "WorktreeCreate",
        }
        result, mock_run = self._run_hook("main", "main", input_data=data)
        self.assertIn("/repo/.claude/worktrees/", result)
        cmd = mock_run.call_args[0][0]
        self.assertTrue(cmd[4].startswith("worktree-"))

    def test_worktree_path_under_claude_dir(self):
        """Worktree is created under .claude/worktrees/ in repo root."""
        result, _ = self._run_hook("main", "main")
        self.assertTrue(
            result.startswith("/repo/.claude/worktrees/"),
        )


if __name__ == "__main__":
    unittest.main()
