#!/usr/bin/env python3
"""Tests for the accept preload script.

Stop-gate tests migrated to test_sprint_stop_gate.py.
Accept-done behavior migrated to test_sprint_start.py (save_sprint.py
now handles .accept clearing and iteration_complete recording as part
of the PostToolUse:Skill replacement plan).
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import (
    create_teammate_worktree_with_commit,
    get_head_sha,
)
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    _IntegrationTestCase,
)

# ===========================================================================
# preload.sh — Accept preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-accept"
    / "scripts"
    / "preload.sh"
)


class TestAcceptPreload(_IntegrationTestCase):
    """M16: preload outputs path, not full sprint content."""

    def test_preload_no_sprint(self):
        """Outputs ERROR when no sprint.json exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_no_stories_to_accept(self):
        """Outputs NO_STORIES_TO_ACCEPT when neither reviewing nor in-progress
        stories exist (story-002 reviewing-first dispatch)."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NO_STORIES_TO_ACCEPT", result.stdout)

    def test_preload_outputs_path_not_content(self):
        """Outputs SPRINT_FILE path, not full sprint content."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Should NOT contain full sprint content
        self.assertNotIn("**Status:** in-progress", result.stdout)

    def test_preload_shows_in_progress_count(self):
        """Outputs count of in-progress stories."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("in-progress", result.stdout.lower())

    def test_preload_clears_accept_marker(self):
        """Preload clears .accept marker so update-story done is unblocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(
            (self.smm_dir / ".accept").exists(),
            ".accept marker should be cleared by preload",
        )


class TestAcceptPreloadInspect(_IntegrationTestCase):
    """story-001: preload surfaces prepare-readiness data for the serial
    main-checkout acceptance flow — enriched TEAMMATE_WORKTREES rows (tip +
    restore ref) and a MAIN_STATE flag when the main checkout needs recovery
    before a detached-HEAD acceptance run."""

    def setUp(self):
        super().setUp()
        # Worktrees live under a gitignored path, so creating one leaves the
        # main tree clean (mirrors production). Commit the ignore so the
        # no-flag assertion sees a clean tree; idempotent across methods.
        (self.tmpdir / ".gitignore").write_text(".claude/worktrees/\n")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=self.tmpdir,
            env=self._test_env,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "ignore worktrees"],
            cwd=self.tmpdir,
            env=self._test_env,
            capture_output=True,
        )

    def _seed_in_progress(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)

    def test_preload_enriches_teammate_rows(self):
        """AC#1: each TEAMMATE_WORKTREES row carries tip SHA + restore ref."""
        self._seed_in_progress()
        wt = create_teammate_worktree_with_commit(
            str(self.tmpdir), "story-001", self._test_env.copy()
        )
        tip = get_head_sha(wt)
        r = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("### TEAMMATE_WORKTREES", r.stdout)
        self.assertIn("story-001\t", r.stdout)
        self.assertIn(f"\t{tip}\tmain", r.stdout)

    def test_preload_no_main_state_flag_when_clean(self):
        """AC#3: clean tree on a normal branch emits no MAIN_STATE flag."""
        self._seed_in_progress()
        create_teammate_worktree_with_commit(
            str(self.tmpdir), "story-001", self._test_env.copy()
        )
        r = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("MAIN_STATE", r.stdout)

    def test_preload_flags_dirty_main(self):
        """AC#2: a dirty main tree surfaces the MAIN_STATE flag."""
        self._seed_in_progress()
        create_teammate_worktree_with_commit(
            str(self.tmpdir), "story-001", self._test_env.copy()
        )
        # Untracked, non-ignored file dirties the tree; the base setUp scrubs
        # it between tests (unlike a modified tracked file, which would leak).
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        r = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MAIN_STATE\tdirty", r.stdout)

    def test_preload_flag_surfaces_solo_dirty(self):
        """Section prints when EITHER rows OR a flag exist — a solo (no
        worktree) dirty tree still surfaces the flag."""
        self._seed_in_progress()
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        r = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("### TEAMMATE_WORKTREES", r.stdout)
        self.assertIn("MAIN_STATE\tdirty", r.stdout)


_SKILL_MD = Path(__file__).parent.parent.parent / "skills" / "xp-accept" / "SKILL.md"


class TestAcceptSkillTextDispatchesToStoryClose(unittest.TestCase):
    """SKILL.md invokes /xp-story-close per done story (commit 9 of the
    JIT/close-unification plan).

    Pre-refactor /xp-accept inlined the merge logic (Step 2b) and the
    auto-switch-to-next-branch logic (Step 2c). Post-refactor those
    move into /xp-story-close, which mirrors /xp-sprint-close shape on
    close_common.py + does its own JIT-create-next dispatch. /xp-accept
    becomes a thin AC-verification + /xp-story-close dispatch step.

    /xp-sprint-review trigger STAYS in /xp-accept (decision e30e9e91e61a
    — single source of truth lives in /xp-accept, not /xp-story-close).
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_invokes_story_close_per_done_story(self):
        # /xp-accept must dispatch to /xp-story-close for each story
        # marked done. The dispatch sentence must explicitly name the
        # skill so a future editor can't silently inline the merge
        # back into /xp-accept.
        self.assertIn(
            "/xp-story-close",
            self.text,
            "/xp-accept must invoke /xp-story-close per done story to "
            "delegate the per-story review + merge + JIT-create-next "
            "pipeline (commit 9 of the JIT/close-unification plan).",
        )

    def test_no_inline_merge_branch_logic(self):
        # The Step 2b merge logic moved to close_common.py via
        # /xp-story-close. /xp-accept must NOT contain merge-branch
        # invocations anymore — that's the regression to catch.
        self.assertNotIn(
            "merge-branch",
            self.text,
            "/xp-accept must NOT inline `branching.py merge-branch` — "
            "merge logic moved to close_common.py invoked by "
            "/xp-story-close. Inline merge here would skip the "
            "close-reviewer fork and PR creation.",
        )

    def test_no_inline_auto_switch_to_next_branch(self):
        # Step 2c auto-switch moved to /xp-story-close JIT-next dispatch.
        # /xp-accept must not branch-switch on its own.
        self.assertNotIn(
            "Auto-Switch",
            self.text,
            "/xp-accept must NOT inline 'Auto-Switch to Next Story' — "
            "JIT-create-next moved to /xp-story-close (which uses "
            "sprint_cli.py next-in-progress + branch_name gating).",
        )

    def test_sprint_review_trigger_remains_in_accept(self):
        # Per decision e30e9e91e61a, /xp-accept owns the single
        # /xp-sprint-review dispatch when the sprint completes —
        # /xp-story-close NEVER fires it. This test pins that the
        # dispatch stays in /xp-accept.
        self.assertIn("/xp-sprint-review", self.text)

    def test_cleanup_teammate_moved_to_story_close(self):
        # Per decision 9029c07ae198: cleanup_teammate.py runs in
        # /xp-story-close per closed story (per-story symmetry), not
        # bulk-after-loop in /xp-accept. /xp-accept must NOT mention
        # the cleanup script anymore — leaves a footgun if an editor
        # adds it back without thinking.
        self.assertNotIn(
            "cleanup_teammate.py",
            self.text,
            "/xp-accept must NOT invoke cleanup_teammate.py — the "
            "cleanup moved to /xp-story-close per closed story for "
            "per-story symmetry (decision 9029c07ae198).",
        )
        self.assertNotIn(
            "Cleanup Teammate Worktrees",
            self.text,
            "Step 5 (Cleanup Teammate Worktrees) moved to /xp-story-close",
        )


class TestAcceptSkillTextInlinesCascadeDefer(unittest.TestCase):
    """SKILL.md must inline the cascade-defer bash, not just describe it.

    Both Step 1 defer paths (automated and manual) tell the agent to
    "cascade the deferral" without showing the mechanics, so each
    invocation re-derives the transitive-dependents bash from scratch.
    Codified after debt 91df34477abe — inline a single shared block.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_cascade_block_present(self):
        # The SKILL.md must contain a fenced code block that performs the
        # cascade — pinned by the simultaneous presence of the
        # find-transitive-dependents subcommand (which walks sprint.json)
        # and an update-story deferred call (which marks each blocked
        # descendant). Splitting on fences avoids accepting distant
        # prose mentions as a "block".
        blocks = re.findall(r"```[a-z]*\n(.*?)\n```", self.text, re.DOTALL)
        cascade_blocks = [
            b
            for b in blocks
            if (
                "find-transitive-dependents" in b
                and "update-story" in b
                and "deferred" in b
            )
        ]
        self.assertTrue(
            cascade_blocks,
            "SKILL.md must contain a fenced code block invoking "
            "sprint_cli.py find-transitive-dependents and looping "
            "update-story <id> deferred over the result. Without it, "
            "both Step 1 defer paths only describe the cascade in prose "
            "and the agent re-derives the algorithm each time — see "
            "debt 91df34477abe.",
        )

    def test_both_step1_paths_reference_cascade_section(self):
        # Both Step 1 sub-paths (Automated lines ~39-61, Manual lines
        # ~63-73) describe the defer choice. Each must point the agent
        # at the shared "Cascading a deferral" section rather than
        # re-explaining the algorithm. Without this, the next prose edit
        # can drift one path's description out of sync with the other.
        # Anchor on the literal cross-reference ("Cascading a deferral")
        # so a header rename forces a coordinated update.
        automated = self._slice_section("### Automated acceptance")
        manual = self._slice_section("### Manual acceptance")
        self.assertIn("Cascading a deferral", automated)
        self.assertIn("Cascading a deferral", manual)
        # And the section itself must exist as a header.
        self.assertIn("### Cascading a deferral", self.text)

    def _slice_section(self, header: str) -> str:
        idx = self.text.find(header)
        self.assertNotEqual(idx, -1, f"SKILL.md missing header: {header}")
        nxt = self.text.find("\n### ", idx + 1)
        return self.text[idx : nxt if nxt != -1 else None]


class TestAcceptPreloadTypes(_IntegrationTestCase):
    """Preload surfaces acceptance_execution type per in-progress story."""

    def _sprint_with_ae(self, ae_type: str) -> str:
        from conftest import _s, _sprint_json

        story = _s(
            "story-001",
            "Test story",
            "in-progress",
            acceptance_execution={"type": ae_type, "command": "test cmd"},
        )
        return _sprint_json([story])

    def test_preload_shows_acceptance_type(self):
        (self.smm_dir / "sprint.json").write_text(self._sprint_with_ae("pytest"))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("story-001: pytest", result.stdout)

    def test_preload_defaults_to_manual(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("story-001: manual", result.stdout)


if __name__ == "__main__":
    unittest.main()
