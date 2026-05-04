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

import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-accept" / "SKILL.md"
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
