#!/usr/bin/env python3
"""Tests for spawn_teammate.py — CLI teammate launcher.

Covers: cleanup_existing, create_worktree, detect_plugin_mode, build_command.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, cleanup_test_worktrees


class TestCleanupExisting(_IntegrationTestCase):
    """cleanup_existing removes old worktree and branch, no-op when absent."""

    def test_no_op_when_worktree_absent(self):
        """No error when worktree doesn't exist."""
        import spawn_teammate

        spawn_teammate.cleanup_existing("teammate-step-99", str(self.tmpdir))

    def test_removes_existing_worktree_and_branch(self):
        """Removes worktree directory and deletes the branch."""
        import spawn_teammate

        name = "teammate-step-1"
        wt_dir = self.tmpdir / ".claude" / "worktrees"
        wt_dir.mkdir(parents=True, exist_ok=True)
        wt_path = str(wt_dir / name)

        subprocess.run(
            ["git", "worktree", "add", "-b", name, wt_path, "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self.assertTrue(Path(wt_path).is_dir())

        spawn_teammate.cleanup_existing(name, str(self.tmpdir))

        self.assertFalse(Path(wt_path).is_dir(), "Worktree dir should be removed")
        result = subprocess.run(
            ["git", "branch", "--list", name],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "", "Branch should be deleted")


class TestCreateWorktree(_IntegrationTestCase):
    """create_worktree creates correct directory and branch."""

    def test_creates_worktree_directory(self):
        """Creates .claude/worktrees/{name} directory."""
        import spawn_teammate

        wt_path = spawn_teammate.create_worktree("teammate-step-1", str(self.tmpdir))
        self.assertTrue(Path(wt_path).is_dir())
        self.assertIn("teammate-step-1", wt_path)

    def test_creates_branch_with_same_name(self):
        """Branch name matches the teammate name."""
        import spawn_teammate

        spawn_teammate.create_worktree("teammate-step-2", str(self.tmpdir))
        result = subprocess.run(
            ["git", "branch", "--list", "teammate-step-2"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertIn("teammate-step-2", result.stdout)

    def test_branches_from_current_branch(self):
        """Worktree branches from current branch, not default."""
        import spawn_teammate

        subprocess.run(
            ["git", "checkout", "-b", "feature/v2"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        (self.tmpdir / "v2.txt").write_text("v2")
        subprocess.run(
            ["git", "add", "v2.txt"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v2"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        wt_path = spawn_teammate.create_worktree("teammate-step-3", str(self.tmpdir))
        self.assertTrue((Path(wt_path) / "v2.txt").is_file())

    def test_idempotent_recreates_worktree(self):
        """If worktree exists, cleans up and recreates."""
        import spawn_teammate

        wt_path1 = spawn_teammate.create_worktree("teammate-step-4", str(self.tmpdir))
        self.assertTrue(Path(wt_path1).is_dir())

        wt_path2 = spawn_teammate.create_worktree("teammate-step-4", str(self.tmpdir))
        self.assertTrue(Path(wt_path2).is_dir())
        self.assertEqual(wt_path1, wt_path2)

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


class TestDetectPluginMode(unittest.TestCase):
    """detect_plugin_mode returns plugin_dir for inline, None for marketplace."""

    def test_inline_mode_returns_plugin_root(self):
        """CLAUDE_PLUGIN_DATA containing 'inline' returns CLAUDE_PLUGIN_ROOT."""
        import spawn_teammate

        plugin_data = "/home/user/.claude/plugins/data/xp-agents-inline/abc"
        plugin_root = "/home/user/.claude/plugins/xp-agents"
        with patch.dict(
            os.environ,
            {
                "CLAUDE_PLUGIN_DATA": plugin_data,
                "CLAUDE_PLUGIN_ROOT": plugin_root,
            },
        ):
            result = spawn_teammate.detect_plugin_mode()
            self.assertEqual(result, plugin_root)

    def test_marketplace_mode_returns_none(self):
        """CLAUDE_PLUGIN_DATA without 'inline' returns None."""
        import spawn_teammate

        plugin_data = "/home/user/.claude/plugins/data/xp-agents-xp/abc"
        with patch.dict(
            os.environ,
            {
                "CLAUDE_PLUGIN_DATA": plugin_data,
            },
            clear=False,
        ):
            env_backup = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            try:
                result = spawn_teammate.detect_plugin_mode()
                self.assertIsNone(result)
            finally:
                if env_backup is not None:
                    os.environ["CLAUDE_PLUGIN_ROOT"] = env_backup

    def test_missing_env_returns_none(self):
        """Missing CLAUDE_PLUGIN_DATA returns None."""
        import spawn_teammate

        with patch.dict(os.environ, {}, clear=True):
            result = spawn_teammate.detect_plugin_mode()
            self.assertIsNone(result)


class TestBuildCommand(unittest.TestCase):
    """build_command constructs correct claude -p arguments."""

    def test_basic_command_flags(self):
        """Command includes --name, --dangerously-skip-permissions, --output-format."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1",
            prompt_file="/tmp/prompt.txt",
            plugin_dir=None,
        )
        self.assertIn("claude", cmd[0])
        self.assertIn("-p", cmd)
        self.assertIn("--name", cmd)
        idx = cmd.index("--name")
        self.assertEqual(cmd[idx + 1], "teammate-step-1")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--output-format", cmd)
        idx = cmd.index("--output-format")
        self.assertEqual(cmd[idx + 1], "stream-json")
        self.assertIn("--verbose", cmd)

    def test_includes_allowed_tools(self):
        """Command includes --allowedTools with expected tools."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1",
            prompt_file="/tmp/prompt.txt",
            plugin_dir=None,
        )
        self.assertIn("--allowedTools", cmd)
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1]
        for tool in ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Skill"):
            self.assertIn(tool, tools)

    def test_plugin_dir_added_when_present(self):
        """--plugin-dir flag added when plugin_dir is not None."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1",
            prompt_file="/tmp/prompt.txt",
            plugin_dir="/path/to/plugin",
        )
        self.assertIn("--plugin-dir", cmd)
        idx = cmd.index("--plugin-dir")
        self.assertEqual(cmd[idx + 1], "/path/to/plugin")

    def test_plugin_dir_omitted_when_none(self):
        """--plugin-dir flag not present when plugin_dir is None."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1",
            prompt_file="/tmp/prompt.txt",
            plugin_dir=None,
        )
        self.assertNotIn("--plugin-dir", cmd)

    def test_prompt_file_as_stdin_redirect(self):
        """Command includes prompt file for stdin redirection."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(
            name="teammate-step-1",
            prompt_file="/tmp/my-prompt.txt",
            plugin_dir=None,
        )
        self.assertIn("--input-file", cmd)
        idx = cmd.index("--input-file")
        self.assertEqual(cmd[idx + 1], "/tmp/my-prompt.txt")


if __name__ == "__main__":
    unittest.main()
