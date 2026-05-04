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
from _branching_fixtures import init_repo, seed_sprint_with_stories


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


class TestFindTeammateWorktreeForStory(unittest.TestCase):
    """find_teammate_worktree_for_story locates the `worktree-story-NNN`
    teammate worktree for a given story id. Returns None when no live
    worktree exists for that story (solo mode, or teammate already
    cleaned up). Powers /xp-story-close's Step 7b cleanup gate.

    Mirrors has_live_teammates' use of `git worktree list --porcelain`
    (real git state, skips prunable entries) but filters by exact
    story-id match instead of just checking for any teammate.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_none_when_no_worktrees(self):
        porcelain = "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertIsNone(
                worktree.find_teammate_worktree_for_story("story-001", str(self.tmpdir))
            )

    def test_returns_worktree_name_when_match(self):
        wt_dir = self.tmpdir / ".claude" / "worktrees" / "worktree-story-042"
        wt_dir.mkdir(parents=True)
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            f"worktree {wt_dir}\nHEAD def\n"
            "branch refs/heads/worktree-story-042\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertEqual(
                worktree.find_teammate_worktree_for_story(
                    "story-042", str(self.tmpdir)
                ),
                "worktree-story-042",
            )

    def test_returns_none_when_other_story_present(self):
        wt_dir = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt_dir.mkdir(parents=True)
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            f"worktree {wt_dir}\nHEAD def\n"
            "branch refs/heads/worktree-story-001\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertIsNone(
                worktree.find_teammate_worktree_for_story("story-002", str(self.tmpdir))
            )

    def test_skips_prunable_entries(self):
        # A prunable worktree-story-NNN should not match — its dir is
        # stale and the cleanup script would fail on it.
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /tmp/.claude/worktrees/worktree-story-099\n"
            "HEAD def\nbranch refs/heads/worktree-story-099\nprunable gitdir\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertIsNone(
                worktree.find_teammate_worktree_for_story("story-099", str(self.tmpdir))
            )

    def test_returns_none_for_non_git_cwd(self):
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(
                worktree.find_teammate_worktree_for_story("story-001", str(non_git))
            )
        finally:
            shutil.rmtree(non_git, ignore_errors=True)

    def test_finds_match_when_not_first_in_list(self):
        # Exercises the loop's continuation past non-matching entries —
        # the target (story-002) appears AFTER another teammate worktree
        # (story-001) in the porcelain output.
        wt001 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt002 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt001.mkdir(parents=True)
        wt002.mkdir(parents=True)
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            f"worktree {wt001}\nHEAD def\n"
            "branch refs/heads/worktree-story-001\n\n"
            f"worktree {wt002}\nHEAD ghi\n"
            "branch refs/heads/worktree-story-002\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertEqual(
                worktree.find_teammate_worktree_for_story(
                    "story-002", str(self.tmpdir)
                ),
                "worktree-story-002",
            )


class TestListLiveTeammateWorktreePaths(unittest.TestCase):
    """list_live_teammate_worktree_paths returns (story_id, abs_path) per
    live teammate worktree.

    Used by /xp-accept's preload after the teammate-merge timing fix —
    the SKILL prose needs to `cd <abs-path>` per story to run that
    teammate's acceptance command in the worktree (where the work lives,
    not in main repo HEAD which lacks the unmerged teammate edits).
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_empty_when_no_teammate_worktrees(self):
        porcelain = "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertEqual(
                worktree.list_live_teammate_worktree_paths(str(self.tmpdir)),
                [],
            )

    def test_returns_story_id_and_abs_path_pairs(self):
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-042"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            f"worktree {wt1}\nHEAD def\n"
            "branch refs/heads/worktree-story-001\n\n"
            f"worktree {wt2}\nHEAD ghi\n"
            "branch refs/heads/worktree-story-042\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertEqual(
                worktree.list_live_teammate_worktree_paths(str(self.tmpdir)),
                [("story-001", str(wt1)), ("story-042", str(wt2))],
            )

    def test_skips_prunable_entries(self):
        wt_live = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt_live.mkdir(parents=True)
        porcelain = (
            "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n\n"
            f"worktree {wt_live}\nHEAD def\n"
            "branch refs/heads/worktree-story-001\n\n"
            "worktree /tmp/.claude/worktrees/worktree-story-099\n"
            "HEAD ghi\nbranch refs/heads/worktree-story-099\nprunable gitdir\n"
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            self.assertEqual(
                worktree.list_live_teammate_worktree_paths(str(self.tmpdir)),
                [("story-001", str(wt_live))],
            )

    def test_returns_empty_for_non_git_cwd(self):
        import shutil

        non_git = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(
                worktree.list_live_teammate_worktree_paths(str(non_git)),
                [],
            )
        finally:
            shutil.rmtree(non_git, ignore_errors=True)


class TestFindClosingTeammateWorktree(unittest.TestCase):
    """find_closing_teammate_worktree picks the live teammate worktree
    whose sprint.json story status is `done` — the implicit-derivation
    discovery used by /xp-story-close to know which teammate worktree
    it's closing without requiring /xp-accept to pass context.

    Returns (abs_path, branch). None when no live teammate worktree
    matches a `done` story (solo flow, or no teammates running).
    Raises ValueError on multi-match (signals broken /xp-accept
    iteration — fail loud, never guess).
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.smm_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _write_sprint(self, stories):
        seed_sprint_with_stories(self.smm_dir, stories)

    def _porcelain_for(self, worktrees):
        """Build `git worktree list --porcelain` for (path, branch) entries.

        After the porcelain-branch refactor, branch is read directly from
        the porcelain output — no separate `git -C path rev-parse` call.
        Tests pass realistic teammate branch names (`<user>/story-NNN`).
        """
        blocks = ["worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"]
        for path, branch in worktrees:
            blocks.append(f"worktree {path}\nHEAD def\nbranch refs/heads/{branch}\n")
        return "\n".join(blocks)

    def test_returns_none_when_no_teammate_worktrees(self):
        self._write_sprint([("story-001", "done")])
        porcelain = "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_returns_none_when_no_done_story(self):
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt.mkdir(parents=True)
        self._write_sprint([("story-001", "in-progress")])
        porcelain = self._porcelain_for([(str(wt), "worktree-story-001")])
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_returns_none_when_only_in_progress_teammates(self):
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        self._write_sprint([("story-001", "in-progress"), ("story-002", "in-progress")])
        # Branch in porcelain reflects realistic teammate naming
        # (`<user>/story-NNN[-slug]`); branch is now read from porcelain
        # directly — no per-worktree git rev-parse spawn.
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_returns_path_and_branch_when_done_with_worktree(self):
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        # story-001 just marked done; story-002 still in-progress.
        self._write_sprint([("story-001", "done"), ("story-002", "in-progress")])
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertEqual(result, (str(wt1), "paulingalls/story-001"))

    def test_raises_when_multiple_done_with_worktrees(self):
        # Signals broken /xp-accept iteration: two done stories with live
        # worktrees should not coexist under the per-story dispatch loop.
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        self._write_sprint([("story-001", "done"), ("story-002", "done")])
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            with self.assertRaises(ValueError) as ctx:
                worktree.find_closing_teammate_worktree(self.smm_dir, str(self.tmpdir))
            self.assertIn("story-001", str(ctx.exception))
            self.assertIn("story-002", str(ctx.exception))

    def test_returns_none_when_worktree_story_not_in_sprint(self):
        # Defensive: a worktree exists for a story-id that's no longer in
        # sprint.json (orphan / stale fixture). Don't raise — treat as no match.
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-999"
        wt.mkdir(parents=True)
        self._write_sprint([("story-001", "done")])
        porcelain = self._porcelain_for([(str(wt), "paulingalls/story-999")])
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        # story-001 has no live worktree; story-999 isn't in sprint.json — no match.
        self.assertIsNone(result)

    def test_returns_none_when_no_sprint_file(self):
        # Solo flow without sprint.json — helper still returns None gracefully.
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt.mkdir(parents=True)
        porcelain = self._porcelain_for([(str(wt), "worktree-story-001")])
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
