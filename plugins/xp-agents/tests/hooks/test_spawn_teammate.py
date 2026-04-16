#!/usr/bin/env python3
"""Tests for spawn_teammate.py — CLI teammate launcher.

Covers: cleanup_existing, create_worktree, build_command, parse_args.
"""

import subprocess
import sys
import unittest
from pathlib import Path

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


class TestBuildCommand(unittest.TestCase):
    """build_command constructs correct claude -p arguments."""

    def test_basic_command_flags(self):
        """Command includes --name, --dangerously-skip-permissions, --output-format."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
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

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertIn("--allowedTools", cmd)
        idx = cmd.index("--allowedTools")
        tools = cmd[idx + 1]
        for tool in ("Read", "Write", "Edit", "Bash", "Grep", "Glob", "Skill"):
            self.assertIn(tool, tools)

    def test_no_plugin_dir_flag(self):
        """Command does not include --plugin-dir (teammate inherits via SMM_DIR env)."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--plugin-dir", cmd)

    def test_no_input_file_flag(self):
        """Command does not include --input-file (prompt piped via stdin)."""
        import spawn_teammate

        cmd = spawn_teammate.build_command(name="teammate-step-1")
        self.assertNotIn("--input-file", cmd)


class TestStoryIdArg(unittest.TestCase):
    """--story-id CLI arg for story attribution."""

    def test_story_id_optional(self):
        """--story-id defaults to None when not provided."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            ["--name", "t1", "--smm-dir", "/smm", "--prompt-file", "/p.txt"]
        )
        self.assertIsNone(args.story_id)

    def test_story_id_accepted(self):
        """--story-id is accepted and stored."""
        import spawn_teammate

        args = spawn_teammate.parse_args(
            [
                "--name",
                "t1",
                "--smm-dir",
                "/smm",
                "--prompt-file",
                "/p.txt",
                "--story-id",
                "story-001",
            ]
        )
        self.assertEqual(args.story_id, "story-001")


class TestStoryAssignmentFile(_IntegrationTestCase):
    """spawn_teammate writes .story-assignment-{name} to SMM dir."""

    def test_writes_story_assignment_when_provided(self):
        """Story assignment file written with correct content."""
        import spawn_teammate
        import worktree

        name = "teammate-step-1"
        assignment = worktree.story_assignment_path(self.smm_dir, name)
        spawn_teammate.write_story_assignment(self.smm_dir, name, "story-001")
        self.assertTrue(assignment.exists())
        self.assertEqual(assignment.read_text().strip(), "story-001")

    def test_no_file_when_story_id_none(self):
        """No story assignment file created when story_id is None."""
        import spawn_teammate
        import worktree

        name = "teammate-step-2"
        assignment = worktree.story_assignment_path(self.smm_dir, name)
        spawn_teammate.write_story_assignment(self.smm_dir, name, None)
        self.assertFalse(assignment.exists())


class TestTeammateIdRemoved(unittest.TestCase):
    """TEAMMATE_ID env var should not be set."""

    def test_no_teammate_id_in_env_setup(self):
        """spawn_teammate source code should not set TEAMMATE_ID."""
        import inspect

        import spawn_teammate

        source = inspect.getsource(spawn_teammate.main)
        self.assertNotIn("TEAMMATE_ID", source)


if __name__ == "__main__":
    unittest.main()
