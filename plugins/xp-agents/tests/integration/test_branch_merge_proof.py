#!/usr/bin/env python3
"""Capstone: absence-proves-merge composes across the branch-delete paths.

Milestone 1 unified branch-delete proof across two shipped stories:
- story-001: worktree.remove_worktree routes branch deletion through
  branch_lifecycle.delete_branch and reports the outcome via BranchRemoval
  (NO_BRANCH / DELETED_MERGED / REFUSED_UNMERGED / FORCE_DROPPED_UNMERGED).
- story-002: cleanup_teammate proves the merge against the recorded story
  base, not HEAD.

Each story has unit tests. This file proves they COMPOSE end to end, through
real git and the real story_done_gate.merged_block keystone on one shared SMM:
a merged branch's absence allows mark-done; an unmerged branch is refused (kept)
and the gate still blocks. Test-only: a broken seam here means STOP and surface
it, not a production patch.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import seed_sprint_with_stories
from conftest import _IntegrationTestCase, cleanup_test_worktrees

# _create_worktree below still mirrors _create_teammate_worktree from
# test_cleanup_teammate_base_proof.py (local copy, not an import — the
# remaining half of consolidation debt 98f1885f1b7b). The two are NOT
# interchangeable, and it's two differences deep, not one:
# 1. Fork point: that copy forks from HEAD, this one from `main` — the
#    base-vs-HEAD distinction is exactly what these merge-proof tests exist
#    to prove. `_worktree_fixtures.make_teammate_worktree` now takes a
#    `start_point` param (default "HEAD") so this half IS consolidatable.
# 2. Placement: both copies place the worktree via
#    `worktree.worktree_path()`, which — under this file's
#    `_IntegrationTestCase` (SMM_DIR pinned in os.environ by setUp) —
#    resolves OUT of the repo (sibling of the SMM dir), matching where
#    `cleanup_teammate.py` / `worktree.remove_worktree` look it up in
#    production. `make_teammate_worktree` instead hardcodes an IN-repo
#    `.claude/worktrees/...` path, unconditionally — by design, since two of
#    its other callers are standalone `unittest.TestCase`s that do NOT pin
#    SMM_DIR in os.environ; routing them through `worktree.worktree_path()`
#    would fall back to running init.sh against the *live* process cwd and
#    leak into the real project's plugin-data dir (see the "containment
#    leak" note in `_bases.py`'s `_IntegrationTestCase.setUp`). Confirmed by
#    direct comparison: the two path constructions diverge whenever SMM_DIR
#    is pinned. So swapping this file's `_create_worktree` for
#    `make_teammate_worktree` would silently create the worktree at the
#    wrong path and break the very cleanup-lookup parity these tests prove.
# Net: the sprint-seeding half is shared, and fork point is now
# parametrizable, but full consolidation is still blocked on placement —
# not a pick-one promotion.


def _create_worktree(tmpdir: Path, name: str, branch: str | None = None) -> str:
    """Create a worktree (forked from `main`) with one commit. Returns its path."""
    import worktree

    branch = branch or name
    # Out-of-repo placement (story-024). worktree_path reads the SMM_DIR the
    # _IntegrationTestCase setUp pins, so this matches where the production
    # cleanup subprocess looks.
    wt = worktree.worktree_path(name, str(tmpdir))
    wt.parent.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt)
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, wt_path, "main"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    (Path(wt_path) / f"{name}.txt").write_text(f"work by {name}")
    subprocess.run(
        ["git", "add", f"{name}.txt"], cwd=wt_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", f"Work by {name}"],
        cwd=wt_path,
        capture_output=True,
        check=True,
    )
    return wt_path


def _merge_into(tmpdir: Path, branch: str, target: str) -> None:
    """Checkout `target`, merge `branch` --no-ff, then return to `main`."""
    subprocess.run(
        ["git", "checkout", target], cwd=tmpdir, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", f"Merge {branch}"],
        cwd=tmpdir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "main"], cwd=tmpdir, capture_output=True, check=True
    )


def _write_sprint_with_stories(
    smm_dir: Path, base_branch: str, stories: "list[tuple[str, str, str]]"
) -> None:
    """Write a stage-2 sprint.json whose branch_name is the base and whose
    stories[] carry the story/stories under test with their branch_name.

    Thin adapter over the shared seeder, taking ``(story_id, status, branch)``
    triples. The sprint body is no longer built here — see
    ``_sprint_fixtures.seed_sprint_with_stories``.
    """
    seed_sprint_with_stories(
        smm_dir,
        [(sid, status) for sid, status, _ in stories],
        base_branch=base_branch,
        story_branches={sid: branch for sid, _, branch in stories},
    )
    (smm_dir / "system_context.json").write_text(
        json.dumps({"branching_strategy": {"stage": 2}})
    )


class TestBranchMergeProofComposes(_IntegrationTestCase):
    """The SEAMS between story-001/002/003 — not a re-test of any one unit."""

    def setUp(self):
        super().setUp()
        self._extra_branches: list[str] = []

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        for name in self._extra_branches:
            subprocess.run(
                ["git", "branch", "-D", name], cwd=self.tmpdir, capture_output=True
            )
        subprocess.run(
            ["git", "checkout", "main"], cwd=self.tmpdir, capture_output=True
        )
        super().tearDown()

    def _create_branch(self, name: str, start: str = "main") -> None:
        subprocess.run(
            ["git", "branch", name, start],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self._extra_branches.append(name)

    def _branch_exists(self, name: str) -> bool:
        return (
            subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{name}"],
                cwd=self.tmpdir,
                capture_output=True,
            ).returncode
            == 0
        )

    def _create_worktree_tracked(self, name: str, branch: str | None = None) -> str:
        wt_path = _create_worktree(self.tmpdir, name, branch=branch)
        self._extra_branches.append(branch or name)
        return wt_path

    # -- 1. merged branch deleted -> gate allows -------------------------

    def test_merged_branch_deleted_then_gate_allows_done(self):
        import story_done_gate
        import worktree

        base = "storybase-701"
        branch = "paulingalls/story-701-thing"
        wt_name = "worktree-story-701"
        story_id = "story-701"

        self._create_branch(base)
        self._create_worktree_tracked(wt_name, branch=branch)
        _merge_into(self.tmpdir, branch, base)

        result = worktree.remove_worktree(wt_name, str(self.tmpdir), merge_target=base)
        self.assertEqual(result, worktree.BranchRemoval.DELETED_MERGED)
        self.assertFalse(self._branch_exists(branch))

        _write_sprint_with_stories(self.smm_dir, base, [(story_id, "closing", branch)])

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        self.assertIsNone(reason, "a merged-then-deleted branch must allow done")

    # -- 2. unmerged branch refused -> gate still blocks ------------------

    def test_unmerged_refused_by_remove_worktree_keeps_branch(self):
        import story_done_gate
        import worktree

        base = "storybase-702"
        branch = "paulingalls/story-702-thing"
        wt_name = "worktree-story-702"
        story_id = "story-702"

        self._create_branch(base)
        self._create_worktree_tracked(wt_name, branch=branch)
        # Deliberately not merged anywhere.

        result = worktree.remove_worktree(
            wt_name, str(self.tmpdir), merge_target=base, force_branch=False
        )
        self.assertEqual(result, worktree.BranchRemoval.REFUSED_UNMERGED)
        self.assertTrue(self._branch_exists(branch), "refused branch must survive")

        _write_sprint_with_stories(self.smm_dir, base, [(story_id, "closing", branch)])

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        self.assertIsNotNone(reason, "a present, unmerged branch must still block done")

    # -- 3. cleanup_teammate proves against the recorded base, not HEAD ---

    def test_cleanup_teammate_merged_to_base_not_head_allows(self):
        import cleanup_teammate
        import story_done_gate

        base = "storybase-704"
        branch = "paulingalls/story-704-thing"
        wt_name = "worktree-story-704"
        story_id = "story-704"

        self._create_branch(base)
        self._create_worktree_tracked(wt_name, branch=branch)
        _merge_into(self.tmpdir, branch, base)

        # Advance HEAD (main) past the base — the merge landed on `base`,
        # not on whatever main happens to be checked out to.
        (self.tmpdir / "unrelated-704.txt").write_text("advance head")
        subprocess.run(
            ["git", "add", "unrelated-704.txt"], cwd=self.tmpdir, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "advance main past base 704"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        _write_sprint_with_stories(self.smm_dir, base, [(story_id, "closing", branch)])

        rc = cleanup_teammate.main(
            [
                "--name",
                wt_name,
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ]
        )
        self.assertEqual(rc, 0, "merged-to-base branch must be cleaned up")
        self.assertFalse(self._branch_exists(branch))

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        self.assertIsNone(
            reason, "merged-to-recorded-base must allow done even past HEAD"
        )

    # -- 4. E2E: two stories, one SMM, discriminated per-branch -----------

    def test_two_stories_one_smm_merged_and_unmerged_compose(self):
        import story_done_gate
        import worktree

        base = "storybase-706"
        branch_a = "paulingalls/story-706a-thing"
        branch_b = "paulingalls/story-706b-thing"
        wt_a = "worktree-story-706a"
        wt_b = "worktree-story-706b"
        story_a = "story-706a"
        story_b = "story-706b"

        self._create_branch(base)

        # story-A: merged into the base, then deleted -> absence proves merge.
        self._create_worktree_tracked(wt_a, branch=branch_a)
        _merge_into(self.tmpdir, branch_a, base)
        result_a = worktree.remove_worktree(wt_a, str(self.tmpdir), merge_target=base)
        self.assertEqual(result_a, worktree.BranchRemoval.DELETED_MERGED)

        # story-B: never merged; remove_worktree refuses to drop it (kept).
        self._create_worktree_tracked(wt_b, branch=branch_b)
        result_b = worktree.remove_worktree(wt_b, str(self.tmpdir), merge_target=base)
        self.assertEqual(result_b, worktree.BranchRemoval.REFUSED_UNMERGED)
        self.assertTrue(self._branch_exists(branch_b), "unmerged branch must survive")

        _write_sprint_with_stories(
            self.smm_dir,
            base,
            [(story_a, "closing", branch_a), (story_b, "closing", branch_b)],
        )

        reason_a = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_a)
        reason_b = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_b)
        self.assertIsNone(reason_a, "the merged-and-deleted story must allow done")
        self.assertIsNotNone(
            reason_b, "the unmerged (present, un-ancestor) story must still block done"
        )


if __name__ == "__main__":
    unittest.main()
