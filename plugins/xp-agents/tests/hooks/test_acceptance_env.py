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

import os
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
    init_repo_with_ignored_worktrees,
    make_conflicted_merge,
)


class TestAcceptanceEnv(unittest.TestCase):
    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        # Mirror production: worktrees live under a gitignored path, so the
        # main tree stays clean once a teammate worktree is created.
        init_repo_with_ignored_worktrees(self.repo)

        self._smm_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # Nest the SMM dir one level down so its PARENT is this test's unique
        # temp — the out-of-repo worktree base is `{smm}.parent/worktrees`
        # (story-024), and a bare temp-root SMM would pile every test's
        # worktree-story-042 into a shared `{tmproot}/worktrees` and collide.
        self.smm = Path(self._smm_td.name) / "smm"
        self.smm.mkdir()
        # Pin SMM_DIR so the in-process create_teammate_worktree_with_commit
        # resolves the same out-of-repo base the assertions below expect,
        # instead of shelling init.sh to the real project (conftest strips it).
        self._prev_smm = os.environ.get("SMM_DIR")
        os.environ["SMM_DIR"] = str(self.smm)

    def tearDown(self):
        if self._prev_smm is None:
            os.environ.pop("SMM_DIR", None)
        else:
            os.environ["SMM_DIR"] = self._prev_smm
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

    # ---- inspect (read-only preload snapshot) -----------------------------

    def test_inspect_enriches_rows_with_tip_and_ref(self):
        wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.rows, [("story-042", wt, get_head_sha(wt), "main")])

    def test_inspect_empty_rows_when_solo(self):
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.rows, [])

    def test_inspect_no_flag_when_clean(self):
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertIsNone(snapshot.main_state)

    def test_inspect_flags_dirty(self):
        (Path(self.repo) / "dirty.txt").write_text("uncommitted")
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.main_state, "dirty")

    def test_inspect_flags_detached_head(self):
        self._git("checkout", "--detach", get_head_sha(self.repo))
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.main_state, "detached-HEAD")

    def test_inspect_flags_in_progress_merge(self):
        make_conflicted_merge(self.repo)
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.main_state, "in-progress-merge")

    def test_inspect_interrupted_takes_precedence_over_dirty(self):
        # A conflicted merge leaves the tree both interrupted AND dirty; the
        # specific recover signal must win over the generic "dirty" flag.
        make_conflicted_merge(self.repo)
        self.assertFalse(branching.is_worktree_clean(self.repo))
        snapshot = acceptance_env.inspect(self.smm, self.repo)
        self.assertEqual(snapshot.main_state, "in-progress-merge")


if __name__ == "__main__":
    unittest.main()
