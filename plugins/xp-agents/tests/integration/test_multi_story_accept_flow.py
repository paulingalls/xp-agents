#!/usr/bin/env python3
"""Capstone E2E for sprint-056: ACCEPT_ACTIVE marker lifecycle.

The per-piece contracts are pinned in their own files (story-001's
TestAcceptMarker in test_pre_tool_write_gates.py; story-004's
TestSprintClosePreload in test_sprint_close.py; story-002's
TestXpAcceptPreloadAcceptActive in test_preload_markers.py). This file
is the single place that walks the full lifecycle in one go — proves
the wiring is correct end-to-end and serves as the canonical regression
fence for c188c64454fd.
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
from _branching_fixtures import get_current_branch_at
from conftest import (
    _extract_preload_var,
    _IntegrationTestCase,
    _make_write_input,
    _s,
    _sprint_json,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_XP_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"
_XP_SPRINT_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"
)
_XP_STORY_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
)
_XP_KICKOFF_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"
)
_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


class TestMultiStoryAcceptFlow(_IntegrationTestCase):
    """E2E sprint-056 acceptance lifecycle."""

    def test_full_lifecycle_arms_suppresses_then_consumes(self):
        # E2E AC + canonical regression guard for c188c64454fd. Walks the
        # full sequence: xp-accept arms the marker, pre_tool_write
        # respects it, xp-sprint-close consumes it, pre_tool_write's
        # gate is restored.
        sprint = _sprint_json(
            [
                _s("story-001", "First", "reviewing"),
                _s("story-002", "Second", "in-progress"),
                _s("story-003", "Third", "in-progress"),
            ],
            sprint_id="sprint-test",
            started="2026-05-04",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)

        # main agent_id (default) — pre_tool_write.run early-returns at
        # is_xp_agent for xp-* subagents, so a teammate-style input
        # would silently skip the gate this lifecycle exercises.
        main_input = _make_write_input(session_id="t", cwd="/tmp")

        # Step 1 (story-002): xp-accept preload arms ACCEPT_ACTIVE
        accept_result = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(
            accept_result.returncode,
            0,
            f"xp-accept preload failed: {accept_result.stderr}",
        )
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Step 2 (story-001): pre_tool_write does NOT re-arm .accept.
        # Pin the trigger precondition so the assertion isn't
        # tautological — without has_in_progress_stories True the
        # gate's input branch never fires, and "absent before, absent
        # after" would pass for the wrong reason.
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

        # Step 3 (story-004): xp-sprint-close consumes ACCEPT_ACTIVE
        close_result = self._run_preload(_XP_SPRINT_CLOSE_PRELOAD)
        self.assertEqual(
            close_result.returncode,
            0,
            f"xp-sprint-close preload failed: {close_result.stderr}",
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Step 4 (gate restored): pre_tool_write re-arms .accept now
        # that the suppressor is gone — proves the marker mechanism is
        # reversible, not a permanent bypass.
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT))


class TestM2TeammateAcceptFlow(_IntegrationTestCase):
    """E2E sprint-057 M-2: teammate-workflow correctness composition.

    Walks the full lifecycle that requires story-001 + story-002 working
    together: xp-accept arms ACCEPT_ACTIVE, pre_tool_write respects it
    during the multi-story window, xp-story-close on a teammate story
    discovers TEAMMATE_CWD + consumes the marker + actually lands the
    teammate's commits via close_common.py merge, and xp-kickoff's
    defensive cleanup catches a stranded marker on the next session.

    Regression fence — turns red only when a future change breaks
    composition across the four pieces (preload contracts, marker
    lifecycle, --cwd routing, fail-loud propagation).
    """

    def _create_teammate_with_commit(self, story_id):
        """Create a teammate worktree with one real commit ready to merge."""
        sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
        import spawn_teammate

        wt_path = spawn_teammate.create_worktree(
            f"worktree-{story_id}", str(self.tmpdir)
        )
        feature = Path(wt_path) / f"{story_id}-feature.txt"
        feature.write_text(f"work for {story_id}")
        env = self._test_env.copy()
        subprocess.run(
            ["git", "add", feature.name],
            cwd=wt_path,
            env=env,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"[{story_id}] add feature"],
            cwd=wt_path,
            env=env,
            capture_output=True,
            check=True,
        )
        return wt_path

    def _git_log_oneline(self, branch):
        return subprocess.run(
            ["git", "log", "--oneline", branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_teammate_close_lifecycle_with_marker_cleanup(self):
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

        # Phase 2: xp-accept preload arms ACCEPT_ACTIVE.
        r = self._run_preload(_XP_ACCEPT_PRELOAD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Phase 3: pre_tool_write fires during the multi-story window —
        # .accept must NOT re-arm. Pin the trigger precondition AND the
        # before-state so the absent-after assertion isn't tautological:
        # has_in_progress_stories=True is what would normally trigger
        # re-arm, ACCEPT absent before proves run() didn't toggle it.
        self.assertTrue(sprint_state.has_in_progress_stories(self.smm_dir))
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        pre_tool_write.run(main_input, smm_dir=self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))

        # Phase 4: mark story-002 done; xp-story-close preload discovers
        # the teammate worktree (TEAMMATE_CWD + CURRENT_BRANCH from the
        # worktree's HEAD, not the orchestrator's) and consumes
        # ACCEPT_ACTIVE on entry.
        sprint_store.update_story_status(self.smm_dir, "story-002", "done")
        sc = self._run_preload(_XP_STORY_CLOSE_PRELOAD)
        self.assertEqual(sc.returncode, 0, sc.stderr)
        teammate_cwd = _extract_preload_var(sc.stdout, "TEAMMATE_CWD")
        self.assertEqual(teammate_cwd, str(Path(wt_path).resolve()))
        self.assertNotEqual(
            _extract_preload_var(sc.stdout, "CURRENT_BRANCH"), orch_branch
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))

        # Phase 5: actually merge via close_common.py. Story-003 caught
        # that merge MUST run at orchestrator cwd (not TEAMMATE_CWD) —
        # `git merge` checks out target which is held by the
        # orchestrator's worktree. The post-merge delete is also a real
        # production gap — close_common.py now skips it when source is
        # held by a teammate worktree (cleanup_teammate.py owns
        # deletion), so the chain must exit 0.
        teammate_branch = _extract_preload_var(sc.stdout, "CURRENT_BRANCH")
        merge = subprocess.run(
            [
                sys.executable,
                str(_CLOSE_COMMON),
                "merge",
                "--cwd",
                str(self.tmpdir),
                "--source",
                teammate_branch,
                "--target",
                orch_branch,
            ],
            cwd=str(self.tmpdir),
            env=self._test_env,
            capture_output=True,
            text=True,
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
        ref = f"refs/heads/{teammate_branch}"
        branch_check = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=self.tmpdir,
            capture_output=True,
        )
        self.assertNotEqual(
            branch_check.returncode,
            0,
            f"teammate branch {teammate_branch} should be deleted after cleanup",
        )

        # Phase 6: simulate a crash/abandon between teammate-story-close
        # and the eventual next-session xp-kickoff — re-arm ACCEPT_ACTIVE
        # manually (some other path could leave it stranded), mark the
        # solo story done so in_progress_count==0, run xp-kickoff. The
        # defensive cleanup from story-001 must clear the marker.
        markers.marker_write(self.smm_dir, markers.ACCEPT_ACTIVE, "")
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        ko = self._run_preload(_XP_KICKOFF_PRELOAD)
        self.assertEqual(ko.returncode, 0, ko.stderr)

        # Phase 7: final state — no ACCEPT_ACTIVE remains, no .accept
        # got stranded during the multi-story window, teammate commit
        # landed (re-asserted from Phase 5 for the AC4 checklist).
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_ACTIVE))
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        self.assertIn("[story-002] add feature", self._git_log_oneline(orch_branch))


if __name__ == "__main__":
    unittest.main()
