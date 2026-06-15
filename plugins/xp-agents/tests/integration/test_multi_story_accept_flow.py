#!/usr/bin/env python3
"""E2E for teammate-workflow lifecycle composition.

Originally the capstone for sprint-056's ACCEPT_ACTIVE marker
lifecycle (TestMultiStoryAcceptFlow); story-004 removed that class
once close-then-done made the marker structurally moot. The
remaining TestM2TeammateAcceptFlow class still pins the multi-story
teammate-close + worktree-cleanup composition — independent value
beyond the marker concern.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import pre_tool_write
import sprint_state
import sprint_store
from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    branch_exists,
    create_teammate_worktree_with_commit,
    get_current_branch_at,
    git_log_oneline_at,
    make_commit,
    merge_teammate_branch,
    write_system_context,
)
from conftest import (
    _extract_preload_var,
    _IntegrationTestCase,
    _make_write_input,
    _s,
    _sprint_json,
)
from integration.conftest import _XP_ACCEPT_PRELOAD, _XP_STORY_CLOSE_PRELOAD

_XP_KICKOFF_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"
)


# [story-004] Deleted TestMultiStoryAcceptFlow — the ACCEPT_ACTIVE
# marker lifecycle it walked is structurally moot under close-then-done.
# Equivalent protection now pinned in test_pre_tool_write_gates.py
# (test_no_rearm_when_reviewing_story_present + the inverse).
# Story-005's capstone (test_incremental_teammate_accept.py) walks the
# end-to-end incremental flow without the marker.


class TestM2TeammateAcceptFlow(_IntegrationTestCase):
    """E2E sprint-057 M-2: teammate-workflow correctness composition.

    Walks the full lifecycle: pre_tool_write does not re-arm .accept
    while a story is in `reviewing` (close-then-done window),
    xp-story-close on a teammate story discovers TEAMMATE_CWD and lands
    the teammate's commits via close_common.py merge, and xp-kickoff
    runs cleanly on the next session.

    Regression fence — turns red only when a future change breaks
    composition across the pieces (preload contracts, reviewing-state
    suppression, --cwd routing, fail-loud propagation). Story-004
    deleted the prior ACCEPT_ACTIVE marker phases; close-then-done
    makes them structurally moot.
    """

    def _create_teammate_with_commit(self, story_id):
        """Backward-compatible thin wrapper around the shared fixture."""
        return create_teammate_worktree_with_commit(
            str(self.tmpdir), story_id, self._test_env.copy()
        )

    def _git_log_oneline(self, branch):
        return git_log_oneline_at(str(self.tmpdir), branch)

    def test_teammate_close_lifecycle(self):
        # Phase 1: setup — 2 in-progress stories, story-002 in a real
        # teammate worktree with a real commit ready to merge.
        sprint = _sprint_json(
            [
                _s("story-001", "Solo story", "in-progress"),
                _s("story-002", "Teammate story", "in-progress"),
            ],
            sprint_id="sprint-test",
            started="2026-05-04",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        wt_path = self._create_teammate_with_commit("story-002")
        orch_branch = get_current_branch_at(self.tmpdir)

        main_input = _make_write_input(session_id="t", cwd="/tmp")

        # Phase 2: xp-accept preload runs cleanly. (Story-004: no marker
        # to arm; close-then-done makes it structurally moot.)
        r = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(r.returncode, 0, r.stderr)

        # Phase 3: promote story-002 to reviewing so close-then-done's
        # has_reviewing_stories suppresses .accept re-arm. Then prove
        # pre_tool_write does NOT re-arm even though story-001 remains
        # in-progress. Pin the trigger preconditions so the absent-after
        # assertion isn't tautological.
        sprint_store.update_story_status(self.smm_dir, "story-002", "reviewing")
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        self.assertTrue(sprint_state.has_reviewing_stories(self.smm_dir))
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

        # Phase 3.5: simulate xp-accept's reviewing→closing promote
        # before /xp-story-close dispatch (closing is the singleton
        # in-pipeline lock; the SKILL prose owns this in production).
        sprint_store.update_story_status(self.smm_dir, "story-002", "closing")

        # Phase 4: invoke xp-story-close preload. Story-002 is in
        # `closing` (Phase 3.5 promote) — preload discovers the teammate
        # worktree by closing-status, emits TEAMMATE_CWD + CURRENT_BRANCH
        # from the worktree's HEAD.
        sc = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(sc.returncode, 0, sc.stderr)
        teammate_cwd = _extract_preload_var(sc.stdout, "TEAMMATE_CWD")
        self.assertEqual(teammate_cwd, str(Path(wt_path).resolve()))
        self.assertNotEqual(
            _extract_preload_var(sc.stdout, "CURRENT_BRANCH"), orch_branch
        )

        # Phase 5: actually merge via close_common.py. Story-003 caught
        # that merge MUST run at orchestrator cwd (not TEAMMATE_CWD) —
        # `git merge` checks out target which is held by the
        # orchestrator's worktree. The post-merge delete is also a real
        # production gap — close_common.py now skips it when source is
        # held by a teammate worktree (cleanup_teammate.py owns
        # deletion), so the chain must exit 0.
        teammate_branch = self._assert_not_none(
            _extract_preload_var(sc.stdout, "CURRENT_BRANCH")
        )
        merge = merge_teammate_branch(
            str(self.tmpdir), teammate_branch, orch_branch, self._test_env
        )
        self.assertEqual(merge.returncode, 0, merge.stderr)
        self.assertIn(
            "skipped delete",
            merge.stdout,
            "merge must skip source delete when teammate worktree holds it",
        )
        log = self._git_log_oneline(orch_branch)
        self.assertIn(
            "[story-002] add feature",
            log,
            "teammate commit must land in orchestrator branch via --cwd routing",
        )

        # Phase 5b: simulate Step 7b — cleanup_teammate.py removes the
        # worktree AND deletes the actual teammate branch (the one
        # close_common.py merge skipped). Story-003 caught a bug here:
        # remove_worktree was deleting by worktree-dir name, leaking
        # the real branch in production. The fix derives branch from
        # HEAD before removal.
        cleanup = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "cleanup_teammate.py"),
                "--name",
                "worktree-story-002",
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ],
            cwd=str(self.tmpdir),
            env=self._test_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
        # Branch is gone (no orphan ref) — the production gap fix.
        self.assertFalse(
            branch_exists(str(self.tmpdir), teammate_branch),
            f"teammate branch {teammate_branch} should be deleted after cleanup",
        )

        # Phase 6: solo story completes; mark it done so in_progress=0.
        # (Story-004 removed the ACCEPT_ACTIVE crash-recovery scenario —
        # marker no longer exists, no defensive cleanup needed.)
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        ko = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(ko.returncode, 0, ko.stderr)

        # Phase 7: final state — no .accept stranded during the multi-
        # story window, teammate commit landed (re-asserted from Phase 5
        # for the AC4 checklist).
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        self.assertIn("[story-002] add feature", self._git_log_oneline(orch_branch))


class TestM6SoloScheduleHandoff(_IntegrationTestCase):
    """story-006 E2E (AC #4): dispatch-ownership split. After a solo story
    merges via close_common.py, the next scheduled story is NOT auto-promoted
    by close — /xp-schedule's promotion primitives (update-story in-progress +
    branching.py create off the merged tip) own that. The SKILL prose
    orchestrates exactly these CLI primitives; this fences the contract.
    """

    def test_close_leaves_next_scheduled_then_schedule_promotes(self):
        # Stage 2 so branching.py create records branch_name (story branches
        # require min stage 2 — the production sprint default).
        write_system_context(self.smm_dir, 2)
        base = get_current_branch_at(self.tmpdir)
        sprint = _sprint_json(
            [
                _s("story-001", "First", "in-progress", branch_name="story-001-b"),
                _s("story-002", "Second", "scheduled", dependencies=["story-001"]),
            ],
            sprint_id="sprint-test",
            started="2026-06-14",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)

        # story-001 lands a real commit on its branch, then closes (merge).
        make_commit(
            str(self.tmpdir), "story-001-b", "f1.txt", "x", "[story-001] add f1"
        )
        merge = merge_teammate_branch(
            str(self.tmpdir), "story-001-b", base, self._test_env
        )
        self.assertEqual(merge.returncode, 0, merge.stderr)

        # Contract 1: close (merge) did NOT promote the next story.
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"],
            "scheduled",
            "close must not promote the next story — /xp-schedule owns promotion",
        )

        # Contract 2: /xp-schedule's solo promotion primitives advance it.
        # (mark story-001 done first — accept Step 4 precedes the post-loop.)
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        sprint_store.update_story_status(self.smm_dir, "story-002", "in-progress")
        create = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "create",
                "--cwd",
                str(self.tmpdir),
                "--story",
                "story-002",
                "--slug",
                "second",
                "--base",
                base,
            ],
            cwd=str(self.tmpdir),
            env=self._test_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(create.returncode, 0, create.stderr)

        promoted = sprint_store.get_story(self.smm_dir, "story-002")
        self.assertEqual(promoted["status"], "in-progress")
        self.assertTrue(
            promoted.get("branch_name"),
            "/xp-schedule's branching.py create must record branch_name",
        )
        self.assertTrue(branch_exists(str(self.tmpdir), promoted["branch_name"]))


if __name__ == "__main__":
    unittest.main()
