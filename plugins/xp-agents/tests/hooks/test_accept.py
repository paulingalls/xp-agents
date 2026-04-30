#!/usr/bin/env python3
"""Tests for the accept preload script.

Stop-gate tests migrated to test_sprint_stop_gate.py.
Accept-done behavior migrated to test_sprint_start.py (save_sprint.py
now handles .accept clearing and iteration_complete recording as part
of the PostToolUse:Skill replacement plan).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

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

    def test_preload_no_in_progress(self):
        """Outputs NO_IN_PROGRESS when no in-progress stories."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NO_IN_PROGRESS", result.stdout)

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


_SKILL_MD = Path(__file__).parent.parent.parent / "skills" / "xp-accept" / "SKILL.md"


class TestAcceptSkillTextDocumentsMarkerConsumption(unittest.TestCase):
    """SKILL.md must document the preload's ACCEPT-marker auto-consumption.

    Without this note, agents hitting an `update-story done` gate elsewhere
    have no signal that the marker is already cleared by the preload —
    leading to silent friction (concern 1180c31dd1ae).
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_preamble_mentions_accept_marker_auto_consumption(self):
        # The preamble must explicitly state that the preload auto-consumes
        # the ACCEPT marker. Loose phrase match (regex) tolerates rewordings
        # but pins the substantive claim.
        pattern = (
            r"(?is)preload[^.\n]{0,200}"
            r"(consume|clear|remove)[^.\n]{0,80}"
            r"(\.accept|ACCEPT marker)"
        )
        self.assertRegex(
            self.text,
            pattern,
            "SKILL.md must document that the preload auto-consumes the "
            "ACCEPT marker — otherwise agents have no signal that the "
            "update-story done gate is already cleared.",
        )


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


class TestAcceptSkillTextRunsTier2SecurityReview(unittest.TestCase):
    """SKILL.md must define the M-2 Tier 2 security-review step.

    Milestone M-2 of the security review tiered migration adds a Tier 2
    cumulative-diff /security-review at /xp-accept before story status
    transitions to done. The enforcement is a prose contract in SKILL.md
    (the LLM judges /security-review's prose findings); these assertions
    pin the contract so a future edit can't silently drop or weaken it.

    Severity convention (Constraints d57963f81ac1, xp-close-reviewer:92):
    Block=high, Concern=medium. Override-of-Block must record severity
    high — silently downgrading hides a consciously-shipped Block.
    """

    _H_1B = "## Step 1b: Concern Triage"
    _H_1C = "## Step 1c: Tier 2 Security Review"
    _H_2 = "## Step 2: Update sprint.json"

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.pos_1b = cls.text.find(cls._H_1B)
        cls.pos_1c = cls.text.find(cls._H_1C)
        cls.pos_2 = cls.text.find(cls._H_2)
        cls.section_1c = cls.text[cls.pos_1c : cls.pos_2]

    def test_step_1c_section_exists(self):
        self.assertIn(
            self._H_1C,
            self.text,
            "/xp-accept must define a Step 1c Tier 2 Security Review "
            "section (M-2). Without this heading, the tiered migration "
            "is not in place at the accept gate.",
        )

    def test_step_1c_after_1b_before_2(self):
        self.assertGreater(self.pos_1b, -1, "Step 1b heading must exist")
        self.assertGreater(self.pos_1c, -1, "Step 1c heading must exist")
        self.assertGreater(self.pos_2, -1, "Step 2 heading must exist")
        self.assertLess(
            self.pos_1b,
            self.pos_1c,
            "Step 1c must appear AFTER Step 1b (Concern Triage runs first)",
        )
        self.assertLess(
            self.pos_1c,
            self.pos_2,
            "Step 1c must appear BEFORE Step 2 (Tier 2 fires before update-story done)",
        )

    def test_step_1c_dispatches_security_review(self):
        # Anchor on the Step 1c section only — Step 0's existing
        # /security-review dispatch must not satisfy this assertion.
        self.assertRegex(
            self.section_1c,
            r'Skill\(\s*skill\s*:\s*"security-review"',
            'Step 1c must invoke Skill(skill: "security-review", ...) '
            "to fire Tier 2 (M-2 contract).",
        )

    def test_step_1c_block_blocks_done(self):
        section = self.section_1c.lower()
        self.assertIn(
            "do not call",
            section,
            "Block path must explicitly say 'do NOT call ... update-story' "
            "so the LLM cannot silently proceed to done on Block findings.",
        )
        self.assertIn(
            "update-story",
            section,
            "Block path must reference update-story (the gated transition).",
        )
        self.assertIn(
            "defer",
            section,
            "Block path must offer 'defer' as a user choice.",
        )
        self.assertIn(
            "override",
            section,
            "Block path must offer 'override' (with concern) as a user choice.",
        )

    def test_step_1c_block_override_records_severity_high(self):
        # Reviewer event db0a57286420: override-of-Block must record
        # severity HIGH (matches xp-close-reviewer:92 + Constraints
        # d57963f81ac1: Block=high). Recording medium silently
        # downgrades a consciously-shipped Block.
        self.assertRegex(
            self.section_1c,
            r'(?is)override.{0,400}--severity\s+["\']?high',
            "Override-of-Block must record --severity high (NOT medium). "
            "Per xp-close-reviewer convention Block=high; downgrading to "
            "medium hides a consciously-shipped Block in the event log.",
        )

    def test_step_1c_concern_records_severity_medium(self):
        # Plain Concern path (NOT the Block-override path) records
        # severity medium per the established convention.
        self.assertRegex(
            self.section_1c,
            r'(?is)concern.{0,400}--severity\s+["\']?medium',
            "Plain Concern path must record --severity medium per the "
            "Block=high/Concern=medium convention.",
        )

    def test_step_1c_skips_when_code_free(self):
        # Reviewer event b9f518ab3b53 + SMM Wisdom 9258988c2d2a: stories
        # with empty file_domain are verification-only / prose-only.
        # Tier 2 against zero code is wasted work and emits a hollow
        # security_complete event. Step 1c must document the skip.
        section = self.section_1c.lower()
        self.assertIn(
            "code_free",
            section,
            "Step 1c must reference code_free (the empty-file_domain "
            "marker) when documenting the skip.",
        )
        self.assertIn(
            "skip",
            section,
            "Step 1c must explicitly say 'skip' for the code_free case.",
        )

    def test_step_1c_distinct_scope_from_step_0(self):
        # Reviewer event 4a0420a09257: Step 0 already invokes
        # /security-review against TEAMMATE_WORKTREES merge slice. Step
        # 1c invokes it against the cumulative story diff. The args
        # string MUST name the cumulative-diff scope so the LLM does
        # not silently reuse Step 0's scope.
        section = self.section_1c.lower()
        self.assertIn(
            "cumulative",
            section,
            "Step 1c args must name 'cumulative' diff scope to "
            "distinguish from Step 0's teammate-merge slice.",
        )
        self.assertIn(
            "merge-base",
            section,
            "Step 1c args must reference 'merge-base' (story branch vs "
            "sprint base) so the scope is unambiguous.",
        )


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
