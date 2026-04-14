#!/usr/bin/env python3
"""Tests for worktree.py — git worktree and path management utilities.

Covers: resolve_git_root, worktree_path, normalize_path.
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

import worktree


class TestResolveGitRoot(unittest.TestCase):
    def setUp(self):
        worktree._clear_git_root_cache()

    def tearDown(self):
        worktree._clear_git_root_cache()

    def test_returns_root_for_git_repo(self):
        """resolve_git_root returns the repo root when cwd is inside a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            result = worktree.resolve_git_root(tmpdir)
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
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            result = worktree.worktree_path("teammate-story-001", tmpdir)
            real = os.path.realpath(tmpdir)
            expected = Path(real) / ".claude" / "worktrees" / "teammate-story-001"
            self.assertEqual(result, expected)

    def test_raises_for_non_git_repo(self):
        """worktree_path raises RuntimeError outside a git repo."""
        with self.assertRaises(RuntimeError):
            worktree.worktree_path("teammate-1", "/")


class TestStoryAssignmentPath(unittest.TestCase):
    def test_returns_dotfile_in_smm_dir(self):
        """story_assignment_path returns {smm_dir}/.story-assignment-{name}."""
        result = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        self.assertEqual(result, Path("/smm/.story-assignment-teammate-step-1"))

    def test_different_names_produce_different_paths(self):
        result_a = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        result_b = worktree.story_assignment_path(Path("/smm"), "teammate-step-2")
        self.assertNotEqual(result_a, result_b)


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
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()
            result = worktree.normalize_path("src/app.ts", tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_absolute_input_inside_repo_returns_relative(self):
        """Absolute path input inside a repo is stripped to relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()
            abs_path = str(src_dir / "app.ts")
            result = worktree.normalize_path(abs_path, tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_old_absolute_events_normalize_to_relative(self):
        """Old absolute paths from events converge to same relative form."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
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
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            result = worktree.normalize_path("src/app.py", tmpdir)
            self.assertEqual(result, "src/app.py")

    def test_nonexistent_nested_file_in_repo_returns_relative(self):
        """Deeply nested non-existent file normalizes to repo-relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            result = worktree.normalize_path("a/b/c/deep.py", tmpdir)
            self.assertEqual(result, "a/b/c/deep.py")

    def test_normalization_consistent_for_existing_and_nonexistent(self):
        """Existing and non-existent files in same dir normalize consistently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "exists.py").touch()
            exists_result = worktree.normalize_path("src/exists.py", tmpdir)
            missing_result = worktree.normalize_path("src/missing.py", tmpdir)
            self.assertEqual(exists_result, "src/exists.py")
            self.assertEqual(missing_result, "src/missing.py")


if __name__ == "__main__":
    unittest.main()
