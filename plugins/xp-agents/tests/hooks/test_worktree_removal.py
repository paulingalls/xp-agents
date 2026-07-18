#!/usr/bin/env python3
"""Tests for worktree.py branch/directory removal.

Split from test_worktree.py (feature split, per the max-500 rule): covers
remove_worktree_dir (directory removal + branch derivation, mock-based) and
remove_worktree (BranchRemoval routing through branch_lifecycle.delete_branch,
real-git fixtures).
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

import worktree
from _branching_fixtures import init_repo


class TestRemoveWorktreeDir(unittest.TestCase):
    """remove_worktree_dir runs git worktree prune to clean up stale entries
    and derives the branch a worktree had checked out. Unchanged by the
    BranchRemoval rewrite — branch DELETION moved to remove_worktree, but
    directory removal + branch derivation still live here.
    """

    def test_prune_runs_after_remove(self):
        """git worktree prune should be called after removal."""
        with (
            patch("worktree.identity.get_current_branch", return_value="teammate-x"),
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            worktree.remove_worktree_dir("teammate-x", "/fake/cwd")
        cmds = [c[0][0][:3] for c in mock_run.call_args_list]
        remove_idx = cmds.index(["git", "worktree", "remove"])
        prune_idx = cmds.index(["git", "worktree", "prune"])
        self.assertGreater(prune_idx, remove_idx, "prune must run after remove")

    def test_prune_runs_even_when_dir_missing(self):
        """Prune should run even when worktree directory is already gone."""
        with (
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/gone/wt")),
            patch.object(Path, "is_dir", return_value=False),
        ):
            worktree.remove_worktree_dir("teammate-y", "/fake/cwd")
        remove_calls = [
            c
            for c in mock_run.call_args_list
            if len(c[0][0]) >= 3 and c[0][0][:3] == ["git", "worktree", "remove"]
        ]
        prune_calls = [
            c
            for c in mock_run.call_args_list
            if c[0][0][:3] == ["git", "worktree", "prune"]
        ]
        self.assertEqual(len(remove_calls), 0, "remove should not run on missing dir")
        self.assertEqual(len(prune_calls), 1, "prune should still run")

    def test_derives_actual_branch_not_worktree_dir_name(self):
        """In production the worktree dir name (`worktree-story-001`) and
        the branch name (`<user>/story-001-<slug>`) diverge. remove_worktree_dir
        must derive the actual branch from HEAD before removing the worktree.
        Falling back to dir name only when derivation genuinely fails
        (detached HEAD, worktree gone).
        """
        with (
            patch(
                "worktree.identity.get_current_branch",
                return_value="paulingalls/story-001-feature",
            ),
            patch("worktree.subprocess.run"),
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            branch = worktree.remove_worktree_dir("worktree-story-001", "/fake/cwd")
        self.assertEqual(branch, "paulingalls/story-001-feature")

    def test_falls_back_to_name_when_head_is_detached(self):
        """Detached HEAD (rev-parse returns 'HEAD') → fall back to dir name."""
        with (
            patch(
                "worktree.identity.get_current_branch",
                return_value="HEAD",
            ),
            patch("worktree.subprocess.run"),
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            branch = worktree.remove_worktree_dir("teammate-detached", "/fake/cwd")
        self.assertEqual(branch, "teammate-detached")

    def test_falls_back_to_name_when_head_derivation_fails(self):
        """Detached HEAD or rev-parse failure → fall back to the worktree
        dir name (legacy contract; covers spawn_teammate's no-branch test
        path where dir name == branch name). identity.get_current_branch
        returns "" on subprocess failure.
        """
        with (
            patch(
                "worktree.identity.get_current_branch",
                return_value="",
            ),
            patch("worktree.subprocess.run"),
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            branch = worktree.remove_worktree_dir("teammate-fallback", "/fake/cwd")
        self.assertEqual(branch, "teammate-fallback")


class TestRemoveWorktree(unittest.TestCase):
    """remove_worktree routes branch deletion through branch_lifecycle.delete_branch
    (proves merge before deleting) and reports what happened via BranchRemoval.
    """

    def setUp(self):
        worktree._clear_git_root_cache()
        self.tmpdir = Path(tempfile.mkdtemp())
        init_repo(str(self.tmpdir))
        # Pin SMM_DIR to an out-of-repo temp so worktree_path resolves the
        # real out-of-repo placement (conftest strips SMM_DIR, which would
        # otherwise shell init.sh non-deterministically). Create AND remove
        # then both funnel through the same out-of-repo path — a genuine
        # round-trip against the new placement (story-024).
        self.base = Path(tempfile.mkdtemp())
        self.smm_dir = self.base / "proj" / "smm"
        self.smm_dir.mkdir(parents=True)
        self._smm_patch = patch.dict(os.environ, {"SMM_DIR": str(self.smm_dir)})
        self._smm_patch.start()

    def tearDown(self):
        import shutil

        from conftest import cleanup_test_worktrees

        cleanup_test_worktrees(self.tmpdir, prefix="worktree-story-")
        self._smm_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.base, ignore_errors=True)
        worktree._clear_git_root_cache()

    def _add_worktree(self, name: str, branch: str | None = None) -> Path:
        branch = branch or name
        wt_path = worktree.worktree_path(name, str(self.tmpdir))
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.tmpdir),
                "worktree",
                "add",
                "-b",
                branch,
                str(wt_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"git worktree add failed: {result.stderr}")
        return wt_path

    def _commit_in(self, path: Path, filename: str, message: str) -> None:
        (path / filename).write_text(message)
        subprocess.run(["git", "add", filename], cwd=str(path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(path),
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test User",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test User",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

    def test_remove_worktree_deletes_merged_branch(self):
        """Branch merged into the passed merge_target -> DELETED_MERGED, branch gone."""
        wt = self._add_worktree("worktree-story-merged", branch="story-merged")
        self._commit_in(wt, "feature.txt", "work")
        subprocess.run(
            ["git", "merge", "--no-ff", "story-merged", "-m", "merge it"],
            cwd=str(self.tmpdir),
            capture_output=True,
        )
        result = worktree.remove_worktree(
            "worktree-story-merged", str(self.tmpdir), merge_target="main"
        )
        self.assertEqual(result, worktree.BranchRemoval.DELETED_MERGED)
        self.assertFalse(
            subprocess.run(
                ["git", "rev-parse", "--verify", "story-merged"],
                cwd=str(self.tmpdir),
                capture_output=True,
            ).returncode
            == 0
        )

    def test_remove_worktree_refuses_unmerged_without_force(self):
        """Unmerged vs merge_target, force_branch=False -> REFUSED_UNMERGED, kept."""
        wt = self._add_worktree("worktree-story-unmerged", branch="story-unmerged")
        self._commit_in(wt, "feature.txt", "work")
        result = worktree.remove_worktree(
            "worktree-story-unmerged",
            str(self.tmpdir),
            merge_target="main",
            force_branch=False,
        )
        self.assertEqual(result, worktree.BranchRemoval.REFUSED_UNMERGED)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "--verify", "story-unmerged"],
                cwd=str(self.tmpdir),
                capture_output=True,
            ).returncode,
            0,
        )

    def test_remove_worktree_force_drops_unmerged_and_signals(self):
        """Unmerged, force_branch=True -> FORCE_DROPPED_UNMERGED, branch gone."""
        wt = self._add_worktree("worktree-story-forced", branch="story-forced")
        self._commit_in(wt, "feature.txt", "work")
        result = worktree.remove_worktree(
            "worktree-story-forced",
            str(self.tmpdir),
            merge_target="main",
            force_branch=True,
        )
        self.assertEqual(result, worktree.BranchRemoval.FORCE_DROPPED_UNMERGED)
        self.assertFalse(
            subprocess.run(
                ["git", "rev-parse", "--verify", "story-forced"],
                cwd=str(self.tmpdir),
                capture_output=True,
            ).returncode
            == 0
        )

    def test_remove_worktree_proves_against_base_not_head(self):
        """Branch merged into merge_target but HEAD advanced past it -> DELETED_MERGED
        (proof is against the passed base, not HEAD)."""
        subprocess.run(
            ["git", "checkout", "-b", "base"],
            cwd=str(self.tmpdir),
            capture_output=True,
        )
        wt = self._add_worktree("worktree-story-base", branch="story-base")
        self._commit_in(wt, "feature.txt", "work")
        subprocess.run(
            ["git", "checkout", "base"], cwd=str(self.tmpdir), capture_output=True
        )
        subprocess.run(
            ["git", "merge", "--no-ff", "story-base", "-m", "merge into base"],
            cwd=str(self.tmpdir),
            capture_output=True,
        )
        subprocess.run(
            ["git", "checkout", "main"], cwd=str(self.tmpdir), capture_output=True
        )
        self._commit_in(self.tmpdir, "unrelated.txt", "unrelated head advance")
        result = worktree.remove_worktree(
            "worktree-story-base", str(self.tmpdir), merge_target="base"
        )
        self.assertEqual(result, worktree.BranchRemoval.DELETED_MERGED)

    def test_remove_worktree_no_branch_returns_no_branch(self):
        """Fully degraded (no out-of-repo base AND non-git cwd) -> NO_BRANCH.

        NO_BRANCH is reached only when worktree_path raises RuntimeError, which
        now requires BOTH the out-of-repo base unresolvable and no git root.
        With a base resolvable, worktree_path never raises on a non-git cwd
        (it needs no git root), so pin the base to None to exercise this path.
        """
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
            with patch("worktree._out_of_repo_worktrees_base", return_value=None):
                result = worktree.remove_worktree("worktree-story-none", str(non_git))
            self.assertEqual(result, worktree.BranchRemoval.NO_BRANCH)
        finally:
            shutil.rmtree(non_git, ignore_errors=True)

    def test_remove_worktree_legacy_no_merge_target_proves_against_head(self):
        """merge_target=None -> proof runs against HEAD (legacy contract)."""
        wt = self._add_worktree(
            "worktree-story-legacy-merged", branch="story-legacy-merged"
        )
        self._commit_in(wt, "feature.txt", "work")
        subprocess.run(
            ["git", "merge", "--no-ff", "story-legacy-merged", "-m", "merge it"],
            cwd=str(self.tmpdir),
            capture_output=True,
        )
        merged_result = worktree.remove_worktree(
            "worktree-story-legacy-merged", str(self.tmpdir)
        )
        self.assertEqual(merged_result, worktree.BranchRemoval.DELETED_MERGED)

        wt2 = self._add_worktree(
            "worktree-story-legacy-unmerged", branch="story-legacy-unmerged"
        )
        self._commit_in(wt2, "feature2.txt", "work2")
        unmerged_result = worktree.remove_worktree(
            "worktree-story-legacy-unmerged", str(self.tmpdir)
        )
        self.assertEqual(unmerged_result, worktree.BranchRemoval.REFUSED_UNMERGED)


if __name__ == "__main__":
    unittest.main()
