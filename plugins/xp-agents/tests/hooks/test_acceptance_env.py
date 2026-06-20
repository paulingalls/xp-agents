#!/usr/bin/env python3
"""Tests for acceptance_env.py — serial main-checkout acceptance mechanics.

Mechanism A: resolve a live teammate story's tip + restore ref, detach the
main checkout onto the tip, restore, and recover an interrupted state.

Each test builds a FRESH per-test git repo (not a shared class-level repo):
these tests mutate HEAD (detach, conflict-merge), and a clean-room repo is
leak-proof by construction — a tearDown that itself depends on
`git merge --abort` / `git checkout` succeeding would be fragile precisely in
the failure modes exercised here.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import acceptance_env
import branching
from _branching_fixtures import (
    GIT_ENV,
    create_teammate_worktree_with_commit,
    get_current_branch,
    get_head_sha,
    init_repo,
    make_conflicted_merge,
)


class TestAcceptanceEnv(unittest.TestCase):
    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo(self.repo)
        # Mirror production: worktrees live under a gitignored path, so the
        # main tree stays clean once a teammate worktree is created.
        (Path(self.repo) / ".gitignore").write_text(".claude/worktrees/\n")
        (Path(self.repo) / "base.txt").write_text("base\n")
        self._git("add", ".gitignore", "base.txt")
        self._git("commit", "-m", "seed")

        self._smm_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.smm = Path(self._smm_td.name)

    def tearDown(self):
        self._repo_td.cleanup()
        self._smm_td.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=GIT_ENV, capture_output=True, text=True
        )

    # ---- resolve_story_tip ------------------------------------------------

    def test_resolve_story_tip_returns_tip_and_base(self):
        wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        tip, base = acceptance_env.resolve_story_tip(self.smm, self.repo, "story-042")
        self.assertEqual(tip, get_head_sha(wt))
        self.assertEqual(base, "main")

    def test_resolve_story_tip_raises_without_live_worktree(self):
        with self.assertRaises(ValueError):
            acceptance_env.resolve_story_tip(self.smm, self.repo, "story-999")

    # ---- checkout_story_tip precondition ----------------------------------

    def test_checkout_story_tip_refuses_dirty_tree(self):
        wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        tip = get_head_sha(wt)
        (Path(self.repo) / "dirty.txt").write_text("uncommitted")
        before = get_head_sha(self.repo)
        with self.assertRaises(ValueError):
            acceptance_env.checkout_story_tip(self.repo, tip)
        # HEAD untouched on refusal.
        self.assertEqual(get_current_branch(self.repo), "main")
        self.assertEqual(get_head_sha(self.repo), before)

    def test_checkout_story_tip_raises_on_bogus_sha(self):
        # Clean tree (passes the dirty precondition), but the SHA doesn't
        # resolve — git checkout fails and the error must surface.
        with self.assertRaises(ValueError):
            acceptance_env.checkout_story_tip(self.repo, "deadbeef" * 5)

    def test_restore_raises_on_missing_ref(self):
        with self.assertRaises(ValueError):
            acceptance_env.restore(self.repo, "no-such-branch")

    # ---- E2E checkout -> restore roundtrip --------------------------------

    def test_checkout_then_restore_roundtrip(self):
        create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        tip, base = acceptance_env.resolve_story_tip(self.smm, self.repo, "story-042")
        self.assertTrue(branching.is_worktree_clean(self.repo))

        acceptance_env.checkout_story_tip(self.repo, tip)
        self.assertEqual(get_current_branch(self.repo), "HEAD")  # detached
        self.assertEqual(get_head_sha(self.repo), tip)
        self.assertTrue(branching.is_worktree_clean(self.repo))

        acceptance_env.restore(self.repo, base)
        self.assertEqual(get_current_branch(self.repo), "main")
        self.assertTrue(branching.is_worktree_clean(self.repo))

    # ---- detect_interrupted -----------------------------------------------

    def test_detect_interrupted_clean(self):
        self.assertIsNone(acceptance_env.detect_interrupted(self.repo))

    def test_detect_interrupted_detached_head(self):
        self._git("checkout", "--detach", get_head_sha(self.repo))
        self.assertEqual(acceptance_env.detect_interrupted(self.repo), "detached-HEAD")

    def test_detect_interrupted_in_progress_merge(self):
        make_conflicted_merge(self.repo)
        self.assertEqual(
            acceptance_env.detect_interrupted(self.repo), "in-progress-merge"
        )

    # ---- recover ----------------------------------------------------------

    def test_recover_from_detached_head_restores_base(self):
        self._git("checkout", "--detach", get_head_sha(self.repo))
        state = acceptance_env.recover(self.smm, self.repo)
        self.assertEqual(state, "detached-HEAD")
        self.assertEqual(get_current_branch(self.repo), "main")  # restore target
        self.assertIsNone(acceptance_env.detect_interrupted(self.repo))

    def test_recover_from_in_progress_merge_aborts_and_restores(self):
        make_conflicted_merge(self.repo)
        state = acceptance_env.recover(self.smm, self.repo)
        self.assertEqual(state, "in-progress-merge")
        self.assertEqual(get_current_branch(self.repo), "main")  # restore target
        self.assertIsNone(acceptance_env.detect_interrupted(self.repo))

    def test_recover_noop_when_clean(self):
        self.assertIsNone(acceptance_env.recover(self.smm, self.repo))
        self.assertEqual(get_current_branch(self.repo), "main")


if __name__ == "__main__":
    unittest.main()
