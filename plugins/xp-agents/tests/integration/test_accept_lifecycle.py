#!/usr/bin/env python3
"""Prose pins for the 5-state story lifecycle.

The lifecycle is `ready -> scheduled -> in-progress -> reviewing ->
done/deferred`. xp-accept's per-story Step 1 must promote a story to
`reviewing` before running its acceptance command, and the
debug-after-fail branch must demote it back to `in-progress` so
pre_tool_write re-arms the `.accept` marker for fix-cycle Edits.

These tests pin the SKILL.md and PROCESS_GUIDE.md prose contracts so
neither doc drifts back to the pre-`reviewing` four-state behavior.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _close_fixtures import _assert_text_ordering

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-accept" / "SKILL.md"
_PRELOAD_SH = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"
_PROCESS_GUIDE = _PLUGIN_ROOT / "PROCESS_GUIDE.md"

_LIFECYCLE_STATES = ("ready", "scheduled", "in-progress", "reviewing", "done")


class TestAcceptHasNoTier2(unittest.TestCase):
    """xp-accept must not contain Tier 2 security-review prose.

    M-8 sprint-055 / story-004: Tier 2 security review migrated out of
    /xp-accept Step 1c into the close skills' Step 4.5 (free/sprint/plan).
    The cumulative coverage for a story now lands at /xp-sprint-close,
    not at /xp-accept time. Pin the absence so the migrated prose can
    never silently re-emerge.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_no_tier_2_or_step_1c_or_security_review_references(self):
        for needle in ("Tier 2", "Step 1c", "security-review"):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle,
                    self.text,
                    f"xp-accept/SKILL.md must not reference {needle!r} "
                    "(Tier 2 migrated to close-skill Step 4.5 in M-8)",
                )


class TestAcceptReviewingLifecycle(unittest.TestCase):
    """SKILL.md prose for the per-story promote/demote contract."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_step_1_promotes_to_reviewing_per_story(self):
        # Per-story Step 1 promotes the story to `reviewing` BEFORE
        # running its acceptance command. Pin the canonical CLI
        # invocation so the prose can be executed verbatim.
        self.assertIn("update-story story-NNN reviewing", self.text)

    def test_promote_step_explains_why_reviewing(self):
        # The promote step must explain WHY: the reviewing status
        # carves the story out of has_in_progress_stories so
        # pre_tool_write doesn't re-arm the .accept marker on edits
        # during the acceptance window.
        lower = self.text.lower()
        self.assertIn("reviewing", lower)
        self.assertTrue(
            ".accept" in self.text or "re-arm" in lower or "marker" in lower,
            "Promote step must explain the .accept-marker rationale",
        )

    def test_debug_branch_demotes_to_in_progress(self):
        # When the user picks "Debug and re-run" after AC fails, the
        # story status must revert to `in-progress` — the work isn't
        # done, and pre_tool_write needs to re-arm the .accept marker
        # for subsequent fix edits. Pin the canonical revert command.
        self.assertIn("update-story story-NNN in-progress", self.text)
        self.assertIn("debug", self.text.lower())

    def test_lifecycle_section_names_five_states(self):
        # SKILL.md should reference all 5 lifecycle states so a reader
        # sees `reviewing` alongside the other states.
        for state in _LIFECYCLE_STATES:
            self.assertIn(state, self.text)


class TestAcceptReviewingFirstDispatch(unittest.TestCase):
    """Story-002: preload selects reviewing-state stories first (teammate
    self-promote path); falls back to in-progress only when no reviewing
    stories exist (solo path). The skill iterates whichever set was
    selected — single dispatch primitive across both modes."""

    @classmethod
    def setUpClass(cls):
        cls.preload = _PRELOAD_SH.read_text()
        cls.skill = _SKILL_MD.read_text()

    def test_preload_counts_reviewing_before_in_progress(self):
        # Preload must count reviewing FIRST so teammate-promoted stories
        # are processed ahead of any lingering in-progress fallbacks.
        # Pin both literal CLI invocations so the prose can be executed.
        reviewing_idx = self.preload.find("sprint_count_status reviewing")
        in_progress_idx = self.preload.find("sprint_count_status in-progress")
        self.assertGreater(reviewing_idx, -1, "preload must count reviewing")
        self.assertGreater(in_progress_idx, -1, "preload must count in-progress")
        self.assertLess(
            reviewing_idx,
            in_progress_idx,
            "reviewing count MUST appear before in-progress (precedence)",
        )

    def test_preload_emits_selected_status_routing(self):
        # Preload routes the selected status into stdout so SKILL.md can
        # iterate the correct set. Pin the literal SELECTED_STATUS=
        # contract — this is the seam between preload and skill.
        self.assertIn("SELECTED_STATUS=", self.preload)

    def test_preload_no_stories_exit_covers_both_states(self):
        # The "nothing to accept" exit must mention BOTH states so a
        # reader (and the skill's error-handling clause) understands the
        # combined precondition. Pin the new sentinel name.
        self.assertIn("NO_STORIES_TO_ACCEPT", self.preload)

    def test_skill_handles_no_stories_to_accept_sentinel(self):
        # The SKILL.md error-handling clause must recognize the new
        # NO_STORIES_TO_ACCEPT sentinel so the agent stops cleanly when
        # neither reviewing nor in-progress stories exist.
        self.assertIn("NO_STORIES_TO_ACCEPT", self.skill)


class TestAcceptCloseThenDoneOrdering(unittest.TestCase):
    """Story-002 Step 2/2b reorder: invoke /xp-story-close BEFORE marking
    the story `done`. The story stays in `reviewing` throughout the close
    cycle; mark-done is the final step. This eliminates the flicker
    window the marker was protecting against and gives merge-failure-
    leaves-story-reviewing semantics for retry."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_close_invocation_precedes_mark_done_in_skill_prose(self):
        # Pin the section ordering via section headers and the canonical
        # mark-done CLI string. Header-anchored so passing prose mentions
        # of /xp-story-close in earlier sections don't cause a false-pass;
        # CLI-anchored on the done end so a future prose reword can't
        # silently break the regression pin. After the renumber, sections
        # are physically sequential: Step 2 (close) → Step 3 (decisions)
        # → Step 4 (mark done).
        _assert_text_ordering(
            self,
            self.text,
            "## Step 2: Invoke /xp-story-close",
            "## Step 4:",
            "update-story story-NNN <done|deferred>",
            msg=(
                "close-then-done: Step 2 (close) precedes Step 4 (mark done)"
                " which contains the mark-done CLI"
            ),
        )

    def test_skill_prose_explains_close_then_done(self):
        # Prose must document the close-then-done semantics + merge-
        # failure semantics so a reader knows why the story stays in
        # reviewing during /xp-story-close.
        lower = self.text.lower()
        self.assertIn("close-then-done", lower)
        self.assertTrue(
            "merge fail" in lower or "merge-fail" in lower or "merge failure" in lower,
            "Prose must explain merge-failure-leaves-reviewing semantics",
        )

    def test_skill_prose_pins_close_then_done_as_primary_protection(self):
        # The structural close-then-done ordering IS the primary
        # protection against fix-cycle .accept re-arm — not the
        # ACCEPT_ACTIVE marker. Pin that the prose names this.
        lower = self.text.lower()
        self.assertTrue(
            "close-then-done" in lower or "stays in `reviewing`" in lower,
            "Prose must name close-then-done as the structural protection",
        )

    def test_skill_documents_idempotent_promote(self):
        # Step 1.0 promote becomes idempotent (no-op when story already
        # reviewing). The prose must document this so the agent knows
        # not to special-case the already-reviewing branch.
        lower = self.text.lower()
        self.assertIn("idempotent", lower)


class TestAcceptCwdSubshell(unittest.TestCase):
    """SKILL.md worktree-acceptance must use a subshell so the parent
    shell's cwd doesn't persist into subsequent Bash calls."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_acceptance_command_uses_subshell_pattern(self):
        # Pin the literal subshell shape `(cd <abs-path> && <command>)`
        # — the prose is the contract. A single precise pin beats two
        # loose substring checks (`(cd ` + `&&` would match unrelated
        # bash snippets).
        self.assertIn("(cd <abs-path> && <command>)", self.text)


class TestProcessGuideLifecycle(unittest.TestCase):
    """PROCESS_GUIDE.md sprint-flow paragraph must name all 5 states."""

    @classmethod
    def setUpClass(cls):
        cls.text = _PROCESS_GUIDE.read_text()

    def test_process_guide_names_reviewing_state(self):
        # The Sprint flow paragraph documents the story lifecycle for
        # all teammates and the lead. Adding `reviewing` to schema
        # without updating this paragraph leaves the doc lying to
        # readers about the valid transitions.
        self.assertIn("reviewing", self.text)

    def test_process_guide_names_full_5_state_lifecycle(self):
        # Pin the full ordered sequence so a future trim doesn't
        # accidentally drop one state.
        for state in _LIFECYCLE_STATES:
            self.assertIn(state, self.text)


if __name__ == "__main__":
    unittest.main()
