#!/usr/bin/env python3
"""E2E for the incremental two-teammate accept flow (M-3 capstone).

Walks the full lifecycle: teammate A self-promotes to reviewing on
clean exit, orchestrator runs xp-accept on A while B is still
in-progress, A goes through close-then-done, intermediate Edits
during the window do NOT arm .accept, B is processed identically
when it finishes. A separate test_merge_failure_leaves_reviewing
covers the merge-failure path.

Composition pin — turns red only when a future change breaks the
M-3 contract across pieces (mechanical promote, reviewing-first
preload dispatch, close-then-done ordering, has_reviewing_stories
suppression of .accept re-arm, source-branch survives merge failure).
"""

import subprocess
import unittest

import branching
import markers
import pre_tool_write
import sprint_state
import sprint_store
from _branching_fixtures import (
    branch_exists,
    create_teammate_worktree_with_commit,
    get_current_branch_at,
    get_head_sha,
    git_log_oneline_at,
    merge_teammate_branch,
    run_accept_env,
)
from conftest import (
    _extract_preload_var,
    _IntegrationTestCase,
    _make_write_input,
    _s,
    _sprint_json,
)
from integration.conftest import _XP_ACCEPT_PRELOAD, _XP_STORY_CLOSE_PRELOAD


class TestIncrementalTeammateAccept(_IntegrationTestCase):
    def test_two_teammate_incremental_flow(self):
        # Phase 1: setup — sprint with two stories both `in-progress`,
        # each with a real teammate worktree + commit. Mirrors the
        # state right after /xp-assign in teammate mode and both
        # teammates have begun work.
        sprint = _sprint_json(
            [
                _s("story-001", "Teammate A story", "in-progress"),
                _s("story-002", "Teammate B story", "in-progress"),
            ],
            sprint_id="sprint-test",
            started="2026-05-07",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        env = self._test_env.copy()
        create_teammate_worktree_with_commit(str(self.tmpdir), "story-001", env)
        create_teammate_worktree_with_commit(str(self.tmpdir), "story-002", env)

        # Phase 2: teammate A exits rc=0 → spawn_teammate.py mechanical-
        # promote fires (the unit pin in test_spawn_teammate.py covers
        # the mechanism; capstone simulates the resulting state via
        # sprint_store directly to keep this composition-focused).
        sprint_store.update_story_status(self.smm_dir, "story-001", "reviewing")

        # AC1: A=reviewing, B=in-progress; predicates reflect both.
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-001")["status"],
            "reviewing",
            "A must self-promote to reviewing on clean exit",
        )
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"],
            "in-progress",
            "B must remain in-progress while A is being accepted",
        )
        self.assertTrue(
            sprint_state.has_reviewing_stories(self.smm_dir),
            "has_reviewing_stories must reflect A",
        )
        self.assertTrue(
            sprint_state.has_in_progress_stories(self.smm_dir),
            "has_in_progress_stories must still reflect B",
        )
        # AC3: actually FIRE pre_tool_write — without invoking it the
        # assertFalse below proves nothing (the marker is only ever
        # written by pre_tool_write). With A reviewing AND B in-
        # progress, has_reviewing_stories suppresses re-arm, so .accept
        # MUST stay absent. This is the structural protection that
        # ACCEPT_ACTIVE used to provide pre-story-004.
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        pre_tool_write.run(_make_write_input(), smm_dir=self.smm_dir)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must not arm while a story is in reviewing",
        )

        # Phase 3: xp-accept preload — reviewing-first dispatch picks A
        # even though B is also active. SELECTED_STATUS=reviewing is the
        # canonical signal the SKILL prose branches on. (AC2)
        result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        # SELECTED_STATUS is the machine-readable contract the SKILL
        # prose branches on. Skip asserting the English summary line —
        # presentation, not contract; brittle against copy edits.
        self.assertEqual(
            _extract_preload_var(result.stdout, "SELECTED_STATUS"),
            "reviewing",
            "preload must select reviewing path while A is in reviewing",
        )

        # Phase 5: A close-then-done. Simulate xp-accept's reviewing→
        # closing promote before dispatching /xp-story-close (closing is
        # the singleton in-pipeline lock; the SKILL prose owns this in
        # production). xp-story-close preload then discovers A's
        # worktree by closing-status; merge_teammate_branch runs
        # close_common.py merge from the orchestrator cwd (helper
        # enforces merge-must-not-run-from-teammate-cwd).
        sprint_store.update_story_status(self.smm_dir, "story-001", "closing")

        # AC3 (literal close-window placement): fire pre_tool_write
        # AFTER the closing transition with A in `closing` and B in
        # `in-progress`. Story-005 extended pre_tool_write's re-arm
        # suppression to cover `closing` too — this exercises the truer
        # in-pipeline window (b02c8303e5e9 re-tightened from the
        # pre-005 workaround that fired before the promote).
        pre_tool_write.run(_make_write_input(), smm_dir=self.smm_dir)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must not arm during the close-then-done window "
            "(closing-state suppression, story-005)",
        )
        orch_branch = get_current_branch_at(self.tmpdir)
        sc = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(sc.returncode, 0, sc.stderr)
        teammate_branch_a = self._assert_not_none(
            _extract_preload_var(sc.stdout, "CURRENT_BRANCH")
        )
        self.assertNotEqual(
            teammate_branch_a,
            orch_branch,
            "preload must surface A's teammate branch, not orchestrator's",
        )
        merge = merge_teammate_branch(
            str(self.tmpdir), teammate_branch_a, orch_branch, self._test_env
        )
        self.assertEqual(merge.returncode, 0, merge.stderr)
        # close_common skips delete when source is held by a teammate
        # worktree — cleanup_teammate.py owns deletion (the sibling
        # test_multi_story_accept_flow exercises that step).
        self.assertIn("skipped delete", merge.stdout)

        # Mark A done — close-then-done's FINAL step (status flip MUST
        # follow the merge so a failed merge can't accidentally complete
        # the story).
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must still not be armed after A's close",
        )

        # Phase 6: B self-promotes when its teammate exits — identical
        # mechanical-promote flow. xp-accept preload now picks B (only
        # remaining reviewing story); xp-story-close + merge follow the
        # same dispatch as A. (AC4 — the "identical processing" pin.)
        # No Phase 4 — what was originally planned as a separate fix-
        # cycle Edit assertion was folded into Phase 2 (the canonical
        # pre_tool_write fence).
        sprint_store.update_story_status(self.smm_dir, "story-002", "reviewing")
        # Pin the dispatch discriminator: A is done AND B is reviewing,
        # so the preload's reviewing-first count must select B (not A).
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-001")["status"],
            "done",
            "A must remain done after its close cycle",
        )
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"],
            "reviewing",
            "B must be the only reviewing story when its preload fires",
        )
        result_b = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(result_b.returncode, 0, result_b.stderr)
        self.assertEqual(
            _extract_preload_var(result_b.stdout, "SELECTED_STATUS"),
            "reviewing",
            "preload must select reviewing path for B (the only reviewing story)",
        )
        # Same reviewing→closing promote as Phase 5 so the closing-keyed
        # discovery finds B.
        sprint_store.update_story_status(self.smm_dir, "story-002", "closing")
        sc_b = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(sc_b.returncode, 0, sc_b.stderr)
        teammate_branch_b = self._assert_not_none(
            _extract_preload_var(sc_b.stdout, "CURRENT_BRANCH")
        )
        merge_b = merge_teammate_branch(
            str(self.tmpdir), teammate_branch_b, orch_branch, self._test_env
        )
        self.assertEqual(merge_b.returncode, 0, merge_b.stderr)
        sprint_store.update_story_status(self.smm_dir, "story-002", "done")

        # Phase 7: final state — sprint complete, no stranded marker,
        # both teammate commits landed on the orchestrator's branch.
        self.assertFalse(
            sprint_state.has_reviewing_stories(self.smm_dir),
            "sprint must have no reviewing stories at completion",
        )
        self.assertFalse(
            sprint_state.has_in_progress_stories(self.smm_dir),
            "sprint must have no in-progress stories at completion",
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must not be stranded after both teammates close",
        )
        log = git_log_oneline_at(str(self.tmpdir), orch_branch)
        self.assertIn(
            "[story-001] add feature",
            log,
            "A's teammate commit must land on the orchestrator branch",
        )
        self.assertIn(
            "[story-002] add feature",
            log,
            "B's teammate commit must land on the orchestrator branch",
        )

    def test_merge_failure_leaves_reviewing(self):
        # AC5: merge-failure path. close_common.py merge sys.exit(1)s
        # on conflict (branching.merge_branch's contract). The story
        # MUST stay in `reviewing` — close_common does not touch sprint
        # state on failure (or success — sprint state is the
        # orchestrator's responsibility), and the source branch survives
        # so the user can resolve and retry.
        sprint = _sprint_json(
            [_s("story-001", "Conflict story", "in-progress")],
            sprint_id="sprint-conflict",
            started="2026-05-07",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        env = self._test_env.copy()

        # Teammate writes feature.txt with content "TEAMMATE".
        wt = create_teammate_worktree_with_commit(
            str(self.tmpdir), "story-001", env, content="TEAMMATE"
        )
        # Orchestrator writes the SAME path with conflicting content.
        # Worktree was branched off HEAD (pre-conflict-commit), so this
        # commit only exists on orchestrator's branch — guaranteed
        # conflict on merge.
        clash = self.tmpdir / "story-001-feature.txt"
        clash.write_text("ORCHESTRATOR")
        subprocess.run(
            ["git", "add", clash.name],
            cwd=self.tmpdir,
            env=env,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "conflicting orchestrator commit"],
            cwd=self.tmpdir,
            env=env,
            capture_output=True,
            check=True,
        )

        # Teammate self-promotes (mechanical), orchestrator dispatches
        # close — but the merge fails.
        sprint_store.update_story_status(self.smm_dir, "story-001", "reviewing")
        orch_branch = get_current_branch_at(self.tmpdir)
        teammate_branch = get_current_branch_at(wt)

        merge = merge_teammate_branch(
            str(self.tmpdir), teammate_branch, orch_branch, env
        )
        self.assertNotEqual(
            merge.returncode,
            0,
            "merge MUST fail when teammate + orch touch the same path",
        )

        # Story stays in reviewing — close_common does not unwind the
        # promote on failure. The orchestrator (xp-accept Step 1.0
        # revert path) owns rollback under user-debug-and-rerun.
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-001")["status"],
            "reviewing",
            "story must stay in reviewing on merge failure (no auto-rollback)",
        )

        # Source branch survives — close_common's chained-step guarantee
        # ("Source branch always survives a failed step so the user can
        # resolve and retry").
        self.assertTrue(
            branch_exists(str(self.tmpdir), teammate_branch),
            f"teammate branch {teammate_branch} must survive a failed merge",
        )


class TestTeammateAcceptMainCheckout(_IntegrationTestCase):
    """story-002: teammate-story acceptance runs in the provisioned MAIN
    checkout via accept-env prepare → run → restore. Own class so the
    HEAD-detaching prepare/restore is isolated from the sibling lifecycle
    tests' committed state in the class-shared repo."""

    def _accept_env(self, *args: str) -> subprocess.CompletedProcess:
        return run_accept_env(self.smm_dir, str(self.tmpdir), *args, env=self._test_env)

    def test_teammate_accept_runs_and_restores_in_main_checkout(self):
        # story-002 AC#2/#3: accept-env prepare detaches the MAIN checkout
        # onto the teammate tip (so the acceptance command runs there, seeing
        # the teammate's files + the provisioned deps), and restore returns to
        # base on EVERY exit path — even after a failing command.
        # Gitignore the worktrees path + commit so the main tree stays clean
        # after the worktree is created (else prepare refuses on a dirty tree).
        (self.tmpdir / ".gitignore").write_text(".claude/worktrees/\n")
        env = self._test_env
        subprocess.run(
            ["git", "add", ".gitignore"], cwd=self.tmpdir, env=env, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "ignore worktrees"],
            cwd=self.tmpdir,
            env=env,
            capture_output=True,
            check=True,
        )
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Teammate story", "in-progress")],
                sprint_id="sprint-test",
                started="2026-06-20",
            )
        )
        wt = create_teammate_worktree_with_commit(
            str(self.tmpdir), "story-001", env.copy()
        )
        base_sha = get_head_sha(str(self.tmpdir))
        tip = get_head_sha(wt)
        self.assertNotEqual(base_sha, tip)

        # prepare: detach main onto the teammate tip; stdout is the restore ref.
        prep = self._accept_env(
            "prepare", "--cwd", str(self.tmpdir), "--story", "story-001"
        )
        self.assertEqual(prep.returncode, 0, prep.stderr)
        self.assertEqual(prep.stdout.strip(), "main")
        self.assertEqual(
            get_head_sha(str(self.tmpdir)), tip, "main detached onto teammate tip"
        )
        self.assertTrue(
            (self.tmpdir / "story-001-feature.txt").exists(),
            "teammate's file is visible in the main checkout after prepare",
        )

        # A FAILING acceptance command must not prevent restore (AC#3).
        self.assertNotEqual(subprocess.run(["false"], cwd=self.tmpdir).returncode, 0)
        restore = self._accept_env(
            "restore", "--cwd", str(self.tmpdir), "--restore-ref", "main"
        )
        self.assertEqual(restore.returncode, 0, restore.stderr)

        # Back on base, clean, teammate file gone from the main worktree.
        self.assertEqual(get_current_branch_at(self.tmpdir), "main")
        self.assertEqual(get_head_sha(str(self.tmpdir)), base_sha)
        self.assertTrue(branching.is_worktree_clean(str(self.tmpdir)))
        self.assertFalse((self.tmpdir / "story-001-feature.txt").exists())


if __name__ == "__main__":
    unittest.main()
