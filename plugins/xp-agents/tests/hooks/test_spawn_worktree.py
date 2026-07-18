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

import spawn_teammate
import worktree
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

        name = "worktree-story-cleanup"
        # Place the worktree where production resolves it (out-of-repo since
        # story-024); the setUp SMM_DIR pin makes worktree_path and
        # cleanup_existing agree on the location.
        wt = worktree.worktree_path(name, str(self.tmpdir))
        wt.parent.mkdir(parents=True, exist_ok=True)
        wt_path = str(wt)

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


class TestRespawnDoesNotDestroyAHandedBranch(_IntegrationTestCase):
    """Re-spawning over a LIVE teammate worktree must not force-delete the
    branch the teammate has been committing to.

    ``cleanup_existing`` ran ``git branch -D <the worktree's HEAD>``
    unconditionally, and ``create_worktree(branch=X)`` calls it FIRST — so a
    re-spawn of a story whose worktree still exists (the teammate crashed, the
    watchdog killed it, a close aborted) force-deleted X with its unmerged
    commits, and then failed to re-add the worktree because the ref it was told
    to check out no longer existed.

    Spawn only OWNS the branch it cuts itself (the no-``branch=`` arm, where
    ``worktree add -b <name>`` re-cuts it). A branch HANDED in was cut by
    /xp-assign and is the teammate's work — spawn deletes nothing.
    """

    def test_respawn_over_live_worktree_preserves_unmerged_work(self):
        import spawn_teammate

        branch = "paulingalls/story-009-live"
        make_commit(str(self.tmpdir), branch, "s9.txt", "s9", "story-009")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        wt_path = spawn_teammate.create_worktree(
            "worktree-story-009", str(self.tmpdir), branch=branch
        )
        # The teammate commits into its worktree; nothing has merged it back.
        (Path(wt_path) / "work.txt").write_text("teammate work")
        subprocess.run(
            ["git", "add", "work.txt"], cwd=wt_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "teammate work"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )
        tip = subprocess.run(
            ["git", "rev-parse", branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # The re-spawn. It must succeed AND leave the work exactly where it was.
        respawned = spawn_teammate.create_worktree(
            "worktree-story-009", str(self.tmpdir), branch=branch
        )

        self.assertEqual(get_current_branch(respawned), branch)
        after = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            after.returncode, 0, "the teammate's branch was force-deleted by a re-spawn"
        )
        self.assertEqual(
            after.stdout.strip(), tip, "the teammate's unmerged commit was destroyed"
        )

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


class TestRespawnDoesNotDestroyUncommittedWork(_IntegrationTestCase):
    """The other half of the same disaster, and the half that was still open.

    Sparing the BRANCH (above) spares what the teammate COMMITTED. The worktree
    DIRECTORY still went away under `git worktree remove --force`, which deletes
    modified and untracked files with it — so a re-spawn over a teammate that was
    still working lost its entire uncommitted tree, and the branch it was spared
    pointed at the last commit before the loss.

    The in-place path took an exclusive claim to stop exactly this
    (`claim_in_place_marker` refuses rather than clobbering a live name). The
    worktree path had no check at all. Git's own non-force refusal is the check:
    it will not remove a tree that holds modified or untracked files.
    """

    def _live_worktree_with_uncommitted_work(self, branch: str) -> Path:
        make_commit(str(self.tmpdir), branch, "base.txt", "base", "story-011")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        wt_path = Path(
            spawn_teammate.create_worktree(
                "worktree-story-011", str(self.tmpdir), branch=branch
            )
        )
        # The teammate is mid-story: edits made, nothing committed yet.
        (wt_path / "in-flight.txt").write_text("hours of uncommitted teammate work")
        return wt_path

    def test_respawn_refuses_rather_than_deleting_uncommitted_work(self):
        branch = "paulingalls/story-011-live"
        wt_path = self._live_worktree_with_uncommitted_work(branch)

        with self.assertRaises(worktree.WorktreeNotEmpty):
            spawn_teammate.create_worktree(
                "worktree-story-011", str(self.tmpdir), branch=branch
            )

        self.assertTrue(wt_path.is_dir(), "the live teammate's worktree was deleted")
        self.assertEqual(
            (wt_path / "in-flight.txt").read_text(),
            "hours of uncommitted teammate work",
            "the live teammate's uncommitted work was destroyed by a re-spawn",
        )

    def test_a_clean_stale_worktree_is_still_cleared(self):
        """The control. Refusing must not break the ordinary re-spawn: a crashed
        teammate that committed everything (or wrote nothing) leaves a CLEAN
        tree, git removes it without --force, and the re-spawn proceeds."""
        branch = "paulingalls/story-012-clean"
        make_commit(str(self.tmpdir), branch, "base.txt", "base", "story-012")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        spawn_teammate.create_worktree(
            "worktree-story-012", str(self.tmpdir), branch=branch
        )
        respawned = spawn_teammate.create_worktree(
            "worktree-story-012", str(self.tmpdir), branch=branch
        )
        self.assertEqual(get_current_branch(respawned), branch)

    def test_post_merge_cleanup_still_forces(self):
        """The caller that legitimately OWNS the tree keeps its force. After the
        merge the story is done and whatever is left (build artifacts, editor
        droppings) is debris — refusing there would wedge every close."""
        name = "worktree-story-013"
        # Out-of-repo placement (story-024); setUp pins SMM_DIR so worktree_path
        # and remove_worktree resolve the same location.
        wt_path = worktree.worktree_path(name, str(self.tmpdir))
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", name, str(wt_path), "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        (wt_path / "build-artifact.o").write_text("debris")

        worktree.remove_worktree(name, str(self.tmpdir), force_branch=True)
        self.assertFalse(wt_path.is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
