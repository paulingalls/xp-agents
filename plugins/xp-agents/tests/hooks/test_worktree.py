#!/usr/bin/env python3
"""Tests for worktree.py — git worktree and path management utilities.

Covers: resolve_git_root, worktree_path, normalize_path, remove_worktree,
has_live_teammates.
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


class TestResolveGitRoot(unittest.TestCase):
    def setUp(self):
        worktree._clear_git_root_cache()

    def tearDown(self):
        worktree._clear_git_root_cache()

    def test_returns_root_for_git_repo(self):
        """resolve_git_root returns the repo root when cwd is inside a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            result = worktree.resolve_git_root(tmpdir)
            assert result is not None
            self.assertEqual(os.path.realpath(result), os.path.realpath(tmpdir))

    def test_returns_none_for_non_repo(self):
        """resolve_git_root returns None when cwd is not in a git repo."""
        result = worktree.resolve_git_root("/")
        self.assertIsNone(result)

    def test_any_os_error_from_git_degrades_to_none_rather_than_escaping(self):
        """A failing git fork must return None, not raise through the caller.

        resolve_git_root sits under normalize_path, which sits under the
        Write/Edit hot path (pre_tool_write.check_working_on_overlap). An
        exception that escapes here does not block the write — it kills the hook
        with a traceback, and PreToolUse treats a non-2 exit as a NON-blocking
        error, so the write is waved through UN-GATED. That is a fail-OPEN in the
        one path that must fail closed.

        FileNotFoundError/NotADirectoryError were caught; every other OSError the
        fork can raise (PermissionError on a non-executable git, EAGAIN under
        fork pressure) was not. The gap hid behind the per-cwd cache: whether it
        fired at all depended on whether some earlier caller had already warmed
        the cache for that cwd, which is why the fail-closed suite that trips it
        (test_write_gate_fails_closed) went flaky under a parallel runner instead
        of simply red.
        """
        with patch.object(
            worktree.subprocess, "check_output", side_effect=OSError("git broke")
        ):
            self.assertIsNone(worktree.resolve_git_root("/some/cwd"))

    def test_caches_per_cwd(self):
        """resolve_git_root caches results per cwd."""
        worktree.resolve_git_root("/")
        worktree.resolve_git_root("/tmp")
        self.assertIn("/", worktree._git_root_cache)
        self.assertIn("/tmp", worktree._git_root_cache)

    def test_clear_cache(self):
        """_clear_git_root_cache empties the cache."""
        worktree.resolve_git_root("/")
        worktree._clear_git_root_cache()
        self.assertEqual(len(worktree._git_root_cache), 0)


class TestWorktreePath(unittest.TestCase):
    def setUp(self):
        worktree._clear_git_root_cache()

    def tearDown(self):
        worktree._clear_git_root_cache()

    def test_returns_path_under_claude_worktrees(self):
        """worktree_path returns {git_root}/.claude/worktrees/{name}."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            result = worktree.worktree_path("teammate-story-001", tmpdir)
            real = os.path.realpath(tmpdir)
            expected = Path(real) / ".claude" / "worktrees" / "teammate-story-001"
            self.assertEqual(result, expected)

    def test_raises_for_non_git_repo(self):
        """worktree_path raises RuntimeError outside a git repo."""
        with self.assertRaises(RuntimeError):
            worktree.worktree_path("teammate-1", "/")


class TestNormalizePath(unittest.TestCase):
    def setUp(self):
        worktree._clear_git_root_cache()

    def tearDown(self):
        worktree._clear_git_root_cache()

    def test_absolute_outside_repo_unchanged(self):
        """Paths outside any git repo stay absolute."""
        result = worktree.normalize_path("/home/user/src/app.ts", "/tmp")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_relative_outside_repo_resolved_to_absolute(self):
        """Relative paths outside any git repo resolve to absolute."""
        result = worktree.normalize_path("src/app.ts", "/home/user")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_dotdot_resolved(self):
        result = worktree.normalize_path("../app.ts", "/home/user/src")
        self.assertEqual(result, "/home/user/app.ts")

    def test_returns_relative_inside_git_repo(self):
        """Inside a git repo, normalize_path strips the repo root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()
            result = worktree.normalize_path("src/app.ts", tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_absolute_input_inside_repo_returns_relative(self):
        """Absolute path input inside a repo is stripped to relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()
            abs_path = str(src_dir / "app.ts")
            result = worktree.normalize_path(abs_path, tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_old_absolute_events_normalize_to_relative(self):
        """Old absolute paths from events converge to same relative form."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()
            abs_result = worktree.normalize_path(str(src_dir / "app.ts"), tmpdir)
            rel_result = worktree.normalize_path("src/app.ts", tmpdir)
            self.assertEqual(abs_result, rel_result)
            self.assertEqual(abs_result, "src/app.ts")

    def test_nonexistent_file_in_repo_returns_relative(self):
        """Non-existent file in a git repo still normalizes to repo-relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            result = worktree.normalize_path("src/app.py", tmpdir)
            self.assertEqual(result, "src/app.py")

    def test_nonexistent_nested_file_in_repo_returns_relative(self):
        """Deeply nested non-existent file normalizes to repo-relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            result = worktree.normalize_path("a/b/c/deep.py", tmpdir)
            self.assertEqual(result, "a/b/c/deep.py")

    def test_normalization_consistent_for_existing_and_nonexistent(self):
        """Existing and non-existent files in same dir normalize consistently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_repo(tmpdir)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "exists.py").touch()
            exists_result = worktree.normalize_path("src/exists.py", tmpdir)
            missing_result = worktree.normalize_path("src/missing.py", tmpdir)
            self.assertEqual(exists_result, "src/exists.py")
            self.assertEqual(missing_result, "src/missing.py")


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

    def tearDown(self):
        import shutil

        from conftest import cleanup_test_worktrees

        cleanup_test_worktrees(self.tmpdir)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        worktree._clear_git_root_cache()

    def _add_worktree(self, name: str, branch: str | None = None) -> Path:
        branch = branch or name
        wt_path = self.tmpdir / ".claude" / "worktrees" / name
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
        """No worktree / non-git cwd -> NO_BRANCH."""
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
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


class TestHasLiveTeammates(unittest.TestCase):
    """has_live_teammates detects teammate worktrees via `git worktree list`."""

    def setUp(self):
        worktree._clear_git_root_cache()
        self.tmpdir = Path(tempfile.mkdtemp())
        init_repo(str(self.tmpdir))

    def tearDown(self):
        import shutil

        from conftest import cleanup_test_worktrees

        cleanup_test_worktrees(self.tmpdir)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        worktree._clear_git_root_cache()

    def _add_worktree(self, name: str) -> Path:
        wt_path = self.tmpdir / ".claude" / "worktrees" / name
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.tmpdir),
                "worktree",
                "add",
                "-b",
                name,
                str(wt_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"git worktree add failed: {result.stderr}")
        return wt_path

    def test_returns_false_for_no_worktrees(self):
        self.assertFalse(worktree.has_live_teammates(str(self.tmpdir)))

    def test_returns_true_for_worktree_story(self):
        self._add_worktree("worktree-story-001")
        self.assertTrue(worktree.has_live_teammates(str(self.tmpdir)))

    def test_ignores_non_teammate_worktrees(self):
        self._add_worktree("feature-branch")
        self.assertFalse(worktree.has_live_teammates(str(self.tmpdir)))

    def test_ignores_old_teammate_pattern(self):
        """Old teammate-* pattern is no longer detected."""
        self._add_worktree("teammate-old")
        self.assertFalse(worktree.has_live_teammates(str(self.tmpdir)))

    def test_skips_prunable_worktree_story(self):
        """Prunable (stale) worktree-story entries should not count as live."""
        import shutil

        wt_path = self._add_worktree("worktree-story-stale")
        shutil.rmtree(wt_path)
        self.assertFalse(worktree.has_live_teammates(str(self.tmpdir)))

    def test_skips_non_prunable_missing_directory(self):
        """Non-prunable entry whose directory is gone should not count."""
        porcelain = (
            "worktree /tmp/main\nHEAD abc123\nbranch refs/heads/main\n\n"
            "worktree /tmp/.claude/worktrees/worktree-story-dead\n"
            "HEAD def456\nbranch refs/heads/worktree-story-dead\n\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertFalse(worktree.has_live_teammates(str(self.tmpdir)))

    def test_returns_false_for_non_git_cwd(self):
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(worktree.has_live_teammates(str(non_git)))
        finally:
            shutil.rmtree(non_git, ignore_errors=True)


class TestBranchHeldByWorktree(unittest.TestCase):
    """branch_held_by_worktree powers close_common.py's skip-delete path
    when the source branch is checked out by a teammate worktree.

    Source held → True (cleanup_teammate.py owns deletion). Source
    absent or held by no live worktree → False (delete proceeds).
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_true_when_branch_held_by_other_worktree(self):
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /tmp/.claude/worktrees/worktree-story-001\n"
            "HEAD def\nbranch refs/heads/paulingalls/story-001\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertTrue(
                worktree.branch_held_by_worktree(
                    str(self.tmpdir), "paulingalls/story-001"
                )
            )

    def test_returns_false_when_branch_not_in_any_worktree(self):
        porcelain = "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertFalse(
                worktree.branch_held_by_worktree(
                    str(self.tmpdir), "paulingalls/story-042"
                )
            )

    def test_substring_match_does_not_count(self):
        # `paulingalls/story-001-feature` must NOT match `paulingalls/story-001`
        # — the helper checks exact `branch refs/heads/<name>` lines.
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /tmp/wt\nHEAD def\n"
            "branch refs/heads/paulingalls/story-001-feature\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertFalse(
                worktree.branch_held_by_worktree(
                    str(self.tmpdir), "paulingalls/story-001"
                )
            )

    def test_returns_false_for_non_git_cwd(self):
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(worktree.branch_held_by_worktree(str(non_git), "anything"))
        finally:
            shutil.rmtree(non_git, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
