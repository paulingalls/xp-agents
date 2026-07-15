#!/usr/bin/env python3
"""Capstone: absence-proves-merge composes across every delete path.

Milestone 1 unified branch-delete proof across three stories:
- story-001: worktree.remove_worktree routes branch deletion through
  branch_lifecycle.delete_branch (NO_BRANCH / DELETED_MERGED /
  REFUSED_UNMERGED / FORCE_DROPPED_UNMERGED).
- story-002: cleanup_teammate proves the merge against the recorded story
  base, not HEAD.
- story-003: a force-drop during re-spawn records a `branch_force_dropped`
  debt event; story_done_gate.merged_block reads it to tell an abandoned
  branch apart from a merged-then-deleted one.

Each story has unit tests. Nothing yet proved they COMPOSE end to end,
through real git and the real gate, on one shared SMM — that's this file.
Test-only: a broken seam here means STOP and surface it, not a production
patch.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import event_schema
from conftest import _IntegrationTestCase, cleanup_test_worktrees

# Mirrors _create_teammate_worktree / _write_sprint_with_branch from
# test_cleanup_teammate_base_proof.py (local copy, not an import — see the
# consolidation debt filed alongside this story). Extended here with
# multi-story sprint seeding, since merged_block needs a specific story's
# `branch_name` rather than just the sprint's recorded base.


def _create_worktree(tmpdir: Path, name: str, branch: str | None = None) -> str:
    """Create a worktree (forked from `main`) with one commit. Returns its path."""
    branch = branch or name
    wt_dir = tmpdir / ".claude" / "worktrees"
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = str(wt_dir / name)
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


def _story(story_id: str, branch_name: str, status: str = "closing") -> dict:
    return {
        "id": story_id,
        "title": "test story",
        "status": status,
        "dependencies": [],
        "milestone_ref": "",
        "design_sources": "",
        "context": "",
        "file_domain": [],
        "interface_contracts": [],
        "acceptance_criteria": [],
        "branch_name": branch_name,
    }


def _write_sprint_with_stories(smm_dir: Path, base_branch: str, stories: list) -> None:
    """Write a stage-2 sprint.json whose branch_name is the base and whose
    stories[] carry the story/stories under test with their branch_name."""
    sprint = {
        "sprint_id": "sprint-1",
        "goal": "test sprint",
        "started": "2026-01-01T00:00:00Z",
        "branch_name": base_branch,
        "stories": stories,
    }
    (smm_dir / "sprint.json").write_text(json.dumps(sprint))
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

        _write_sprint_with_stories(self.smm_dir, base, [_story(story_id, branch)])

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

        _write_sprint_with_stories(self.smm_dir, base, [_story(story_id, branch)])

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        self.assertIsNotNone(reason, "a present, unmerged branch must still block done")

    # -- 3. force-dropped unmerged -> gate blocks as abandoned ------------

    def test_force_dropped_unmerged_then_gate_blocks_abandoned(self):
        import spawn_teammate
        import story_done_gate
        import worktree

        base = "storybase-703"
        branch = "paulingalls/story-703-thing"
        wt_name = "worktree-story-703"
        story_id = "story-703"

        self._create_branch(base)
        self._create_worktree_tracked(wt_name, branch=branch)

        removal, drop_id = spawn_teammate.cleanup_existing(
            wt_name,
            str(self.tmpdir),
            owns_branch=True,
            smm_dir=self.smm_dir,
            story_id=story_id,
        )
        self.assertEqual(removal, worktree.BranchRemoval.FORCE_DROPPED_UNMERGED)
        self.assertIsNotNone(drop_id)
        self.assertFalse(self._branch_exists(branch))

        events, _ = _common.load_events_with_resolutions(self.smm_dir)
        drops = [
            e
            for e in events
            if e.get("type") == _common.DEBT
            and (e.get("metadata") or {}).get("action")
            == event_schema.DEBT_ACTION_BRANCH_FORCE_DROPPED
            and (e.get("metadata") or {}).get("branch") == branch
        ]
        self.assertEqual(len(drops), 1, "cleanup_existing must record exactly one drop")

        _write_sprint_with_stories(self.smm_dir, base, [_story(story_id, branch)])

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        reason = self._assert_not_none(
            reason, "a force-dropped-unmerged branch must block as abandoned"
        )
        self.assertIn("--force-unmerged", reason)

    # -- 4. cleanup_teammate proves against the recorded base, not HEAD ---

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

        _write_sprint_with_stories(self.smm_dir, base, [_story(story_id, branch)])

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

    # -- 5. force-drop then successful re-create -> permanent-block guard --

    def test_reworked_after_force_drop_allows_done(self):
        import spawn_teammate
        import story_done_gate

        # Dir name == branch name: the owns-branch (`branch=None`) convention
        # create_worktree re-cuts under, so the re-created branch matches the
        # one force-dropped.
        name = "worktree-story-705"
        story_id = "story-705"

        self._create_worktree_tracked(name)

        # One call: cleanup_existing (inside create_worktree) force-drops the
        # stale unmerged branch (writes R), then the re-add succeeds and
        # records the supersede (S resolving R).
        spawn_teammate.create_worktree(
            name,
            str(self.tmpdir),
            branch=None,
            smm_dir=self.smm_dir,
            story_id=story_id,
        )

        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        drops = [
            e
            for e in events
            if e.get("type") == _common.DEBT
            and (e.get("metadata") or {}).get("action")
            == event_schema.DEBT_ACTION_BRANCH_FORCE_DROPPED
        ]
        self.assertEqual(len(drops), 1)
        self.assertIn(
            drops[0]["id"],
            resolutions["resolved_debt_ids"],
            "the re-create must supersede the force-drop record",
        )

        # `main` is both the recorded base and the branch the re-created
        # worktree forked from with no new commits, so it trivially reads as
        # merged into it.
        _write_sprint_with_stories(self.smm_dir, "main", [_story(story_id, name)])

        reason = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_id)
        self.assertIsNone(
            reason, "a reworked-and-recreated branch must not stay permanently blocked"
        )

    # -- 6. E2E: two stories, one SMM, discriminated per-branch -----------

    def test_two_stories_one_smm_merged_and_abandoned_compose(self):
        import spawn_teammate
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

        self._create_worktree_tracked(wt_a, branch=branch_a)
        _merge_into(self.tmpdir, branch_a, base)
        result_a = worktree.remove_worktree(wt_a, str(self.tmpdir), merge_target=base)
        self.assertEqual(result_a, worktree.BranchRemoval.DELETED_MERGED)

        self._create_worktree_tracked(wt_b, branch=branch_b)
        removal_b, drop_id_b = spawn_teammate.cleanup_existing(
            wt_b,
            str(self.tmpdir),
            owns_branch=True,
            smm_dir=self.smm_dir,
            story_id=story_b,
        )
        self.assertEqual(removal_b, worktree.BranchRemoval.FORCE_DROPPED_UNMERGED)
        self.assertIsNotNone(drop_id_b)

        _write_sprint_with_stories(
            self.smm_dir, base, [_story(story_a, branch_a), _story(story_b, branch_b)]
        )

        reason_a = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_a)
        reason_b = story_done_gate.merged_block(self.smm_dir, str(self.tmpdir), story_b)
        self.assertIsNone(reason_a, "the merged-and-deleted story must allow done")
        self.assertIsNotNone(
            reason_b, "the abandoned (force-dropped) story must still block done"
        )


if __name__ == "__main__":
    unittest.main()
