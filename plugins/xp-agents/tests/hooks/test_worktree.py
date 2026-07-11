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


class TestRemoveWorktree(unittest.TestCase):
    """remove_worktree runs git worktree prune to clean up stale entries."""

    def test_prune_runs_after_remove(self):
        """git worktree prune should be called after removal."""
        with (
            patch("worktree.identity.get_current_branch", return_value="teammate-x"),
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            worktree.remove_worktree("teammate-x", "/fake/cwd")
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
            worktree.remove_worktree("teammate-y", "/fake/cwd")
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

    def test_deletes_actual_branch_not_worktree_dir_name(self):
        """In production the worktree dir name (`worktree-story-001`) and
        the branch name (`<user>/story-001-<slug>`) diverge. remove_worktree
        must derive the actual branch from HEAD before removing the worktree
        and pass it to `git branch -d`. Falling back to dir name only when
        derivation genuinely fails (detached HEAD, worktree gone).
        """
        with (
            patch(
                "worktree.identity.get_current_branch",
                return_value="paulingalls/story-001-feature",
            ),
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            worktree.remove_worktree("worktree-story-001", "/fake/cwd")
        # Find the `git branch -d/D <name>` call.
        branch_calls = [
            c[0][0]
            for c in mock_run.call_args_list
            if len(c[0][0]) >= 2 and c[0][0][:2] == ["git", "branch"]
        ]
        self.assertEqual(len(branch_calls), 1)
        self.assertEqual(branch_calls[0][-1], "paulingalls/story-001-feature")

    def test_falls_back_to_name_when_head_is_detached(self):
        """Detached HEAD (rev-parse returns 'HEAD') → fall back to dir name."""
        with (
            patch(
                "worktree.identity.get_current_branch",
                return_value="HEAD",
            ),
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            worktree.remove_worktree("teammate-detached", "/fake/cwd")
        branch_calls = [
            c[0][0]
            for c in mock_run.call_args_list
            if len(c[0][0]) >= 2 and c[0][0][:2] == ["git", "branch"]
        ]
        self.assertEqual(len(branch_calls), 1)
        self.assertEqual(branch_calls[0][-1], "teammate-detached")

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
            patch("worktree.subprocess.run") as mock_run,
            patch("worktree.worktree_path", return_value=Path("/fake/wt")),
            patch.object(Path, "is_dir", return_value=True),
        ):
            worktree.remove_worktree("teammate-fallback", "/fake/cwd")
        branch_calls = [
            c[0][0]
            for c in mock_run.call_args_list
            if len(c[0][0]) >= 2 and c[0][0][:2] == ["git", "branch"]
        ]
        self.assertEqual(len(branch_calls), 1)
        self.assertEqual(branch_calls[0][-1], "teammate-fallback")


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
