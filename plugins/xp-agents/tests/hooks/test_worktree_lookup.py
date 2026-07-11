#!/usr/bin/env python3
"""Tests for worktree.py teammate-worktree lookup helpers.

Covers: find_teammate_worktree_for_story, list_live_teammate_worktree_paths,
find_closing_teammate_worktree.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from _branching_fixtures import seed_sprint_with_stories


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
    whose sprint.json story status is `closing` — the implicit-
    derivation discovery used by /xp-story-close to know which teammate
    worktree it's closing without requiring /xp-accept to pass context.

    `closing` is the singleton in-pipeline lock; `reviewing` is plural-
    safe so concurrent teammate self-promotes can coexist. Returns
    (abs_path, branch). None when no live teammate worktree matches a
    closing story. Raises ValueError on multi-closing (signals broken
    /xp-accept iteration — fail loud, never guess which to close).
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
        self._write_sprint([("story-001", "closing")])
        porcelain = "worktree /tmp/main\nHEAD abc\nbranch refs/heads/main\n"
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_returns_none_when_no_closing_story(self):
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt.mkdir(parents=True)
        self._write_sprint([("story-001", "in-progress")])
        porcelain = self._porcelain_for([(str(wt), "worktree-story-001")])
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_returns_none_when_done_with_worktree(self):
        # Inverse-regression pin: a `done` story's worktree must NOT
        # match — mark-done is the FINAL step AFTER /xp-story-close, so
        # by the time a story is done its worktree should already be
        # cleaned up. Pinning the exclusion guards against a future
        # regression flipping the discovery query back to `done`.
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt.mkdir(parents=True)
        self._write_sprint([("story-001", "done")])
        porcelain = self._porcelain_for([(str(wt), "paulingalls/story-001")])
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

    def test_returns_path_and_branch_when_closing_with_worktree(self):
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        self._write_sprint([("story-001", "closing"), ("story-002", "in-progress")])
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertEqual(result, (str(wt1), "paulingalls/story-001"))

    def test_returns_closing_when_concurrent_reviewing_present(self):
        # Multiple reviewing worktrees plus one closing → return the
        # closing worktree, no raise. Reviewing is plural-safe; only
        # `closing` is the singleton lock.
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt3 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-003"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        wt3.mkdir(parents=True)
        self._write_sprint(
            [
                ("story-001", "reviewing"),
                ("story-002", "reviewing"),
                ("story-003", "closing"),
            ]
        )
        porcelain = self._porcelain_for(
            [
                (str(wt1), "paulingalls/story-001"),
                (str(wt2), "paulingalls/story-002"),
                (str(wt3), "paulingalls/story-003"),
            ]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertEqual(result, (str(wt3), "paulingalls/story-003"))

    def test_returns_none_when_only_reviewing_stories(self):
        # Reviewing-status worktrees must never match — only `closing`
        # triggers the discovery. Multiple reviewing + zero closing → None.
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        self._write_sprint([("story-001", "reviewing"), ("story-002", "reviewing")])
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            result = worktree.find_closing_teammate_worktree(
                self.smm_dir, str(self.tmpdir)
            )
        self.assertIsNone(result)

    def test_raises_when_multiple_closing_with_worktrees(self):
        # Two `closing` stories with live worktrees signals a broken
        # iteration — fail loud, never guess which to close.
        wt1 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-001"
        wt2 = self.tmpdir / ".claude" / "worktrees" / "worktree-story-002"
        wt1.mkdir(parents=True)
        wt2.mkdir(parents=True)
        self._write_sprint([("story-001", "closing"), ("story-002", "closing")])
        porcelain = self._porcelain_for(
            [(str(wt1), "paulingalls/story-001"), (str(wt2), "paulingalls/story-002")]
        )
        with patch("worktree.subprocess.check_output", return_value=porcelain):
            with self.assertRaises(ValueError) as ctx:
                worktree.find_closing_teammate_worktree(self.smm_dir, str(self.tmpdir))
            self.assertIn("story-001", str(ctx.exception))
            self.assertIn("story-002", str(ctx.exception))
            self.assertIn("closing", str(ctx.exception))

    def test_returns_none_when_worktree_story_not_in_sprint(self):
        # Defensive: a worktree exists for a story-id that's no longer in
        # sprint.json (orphan / stale fixture). Don't raise — treat as no match.
        wt = self.tmpdir / ".claude" / "worktrees" / "worktree-story-999"
        wt.mkdir(parents=True)
        self._write_sprint([("story-001", "closing")])
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
