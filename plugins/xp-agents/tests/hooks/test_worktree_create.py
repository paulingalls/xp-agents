#!/usr/bin/env python3
"""Tests for WorktreeCreate hook: branch base customization."""

import subprocess
import unittest
from unittest import mock

_INPUT = {
    "session_id": "test",
    "cwd": "/repo",
    "branch": "worktree-abc",
    "worktree_path": "/tmp/wt-abc",
    "isolation": "worktree",
}


class TestWorktreeCreate(unittest.TestCase):
    """WorktreeCreate hook creates worktree from current branch."""

    def setUp(self):
        import importlib
        import sys
        from pathlib import Path

        scripts = Path(__file__).parent.parent.parent / "scripts"
        sys.path.insert(0, str(scripts))
        import worktree_create

        importlib.reload(worktree_create)
        self.worktree_create = worktree_create

    def _run_hook(self, current: str, default: str) -> tuple[str, mock.MagicMock]:
        """Run hook with mocked branch detection. Returns (result, mock_run)."""
        with (
            mock.patch.object(
                self.worktree_create, "_get_current_branch", return_value=current
            ),
            mock.patch.object(
                self.worktree_create, "_get_default_branch", return_value=default
            ),
            mock.patch("subprocess.run") as mock_run,
        ):
            result = self.worktree_create.run(_INPUT)
            return result, mock_run

    def test_creates_from_current_branch_when_differs_from_default(self):
        """On v2 with default=main, worktree branches from v2."""
        result, mock_run = self._run_hook("v2", "main")
        self.assertEqual(result, "/tmp/wt-abc")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[-1], "v2")

    def test_creates_with_default_when_branches_match(self):
        """On main with default=main, no base ref appended."""
        _, mock_run = self._run_hook("main", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            ["git", "worktree", "add", "-b", "worktree-abc", "/tmp/wt-abc"],
        )

    def test_handles_missing_remote_gracefully(self):
        """No origin/HEAD returns empty default, creates without base ref."""
        _, mock_run = self._run_hook("v2", "")
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("v2", cmd)

    def test_handles_detached_head(self):
        """Detached HEAD returns empty current, creates without base ref."""
        _, mock_run = self._run_hook("", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            ["git", "worktree", "add", "-b", "worktree-abc", "/tmp/wt-abc"],
        )

    def test_returns_worktree_path(self):
        """run() returns the worktree_path from input."""
        result, _ = self._run_hook("main", "main")
        self.assertEqual(result, "/tmp/wt-abc")

    def test_fails_when_git_worktree_add_fails(self):
        """CalledProcessError propagates when git worktree add fails."""
        with (
            mock.patch.object(
                self.worktree_create, "_get_current_branch", return_value="v2"
            ),
            mock.patch.object(
                self.worktree_create, "_get_default_branch", return_value="main"
            ),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.worktree_create.run(_INPUT)

    def test_git_stdout_suppressed(self):
        """git worktree add stdout is DEVNULL to avoid polluting hook output."""
        _, mock_run = self._run_hook("v2", "main")
        kwargs = mock_run.call_args[1]
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
