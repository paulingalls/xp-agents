#!/usr/bin/env python3
"""Tests for spawn_teammate.py — worktree creation and cleanup.

Extracted from test_spawn_teammate.py to stay under 500-line file limit.
Covers: cleanup_existing, create_worktree, create_worktree with branch=.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import get_current_branch, make_commit
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


class TestCreateWorktreeWithBranch(_IntegrationTestCase):
    """create_worktree with branch= checks out an existing branch."""

    def test_checks_out_existing_branch(self):
        """When branch= is provided, worktree is on the specified branch."""
        import spawn_teammate

        branch_name = "paulingalls/story-001-test"
        make_commit(str(self.tmpdir), branch_name, "s1.txt", "s1", "story-001")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        wt_path = spawn_teammate.create_worktree(
            "teammate-step-1", str(self.tmpdir), branch=branch_name
        )
        self.assertEqual(get_current_branch(wt_path), branch_name)

    def test_no_teammate_branch_created(self):
        """When branch= is provided, no teammate-* branch is created."""
        import spawn_teammate

        branch_name = "paulingalls/story-002-test"
        make_commit(str(self.tmpdir), branch_name, "s2.txt", "s2", "story-002")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        spawn_teammate.create_worktree(
            "teammate-step-1", str(self.tmpdir), branch=branch_name
        )
        result = subprocess.run(
            ["git", "branch", "--list", "teammate-step-1"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_without_branch_unchanged(self):
        """Backward compat: without branch=, creates teammate-* branch as before."""
        import spawn_teammate

        wt_path = spawn_teammate.create_worktree("teammate-step-1", str(self.tmpdir))
        result = subprocess.run(
            ["git", "branch", "--list", "teammate-step-1"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertIn("teammate-step-1", result.stdout)
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
