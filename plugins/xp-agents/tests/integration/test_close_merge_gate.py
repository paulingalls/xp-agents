#!/usr/bin/env python3
"""Close-pipeline SKILL.md auto-merge override section (Commit 4).

Split out of the original test_close_merge_gate.py (which grew past
the 500-line cap). This file keeps the auto-merge override assertions
— the SKILL.md section itself (story+free carry it, sprint+plan do
not) and its gate conditions (tests green, TEST_COMMAND var, discovery
hint, count-classifications usage, design_decision guard, cycle-id
scoping).

TEST_COMMAND preload emission tests live in
test_close_merge_gate_test_command.py. The deterministic Step 6
count-concerns CLI realistic E2E tests live in
test_close_merge_gate_count_concerns_e2e.py.

Per-mode shared-content preload emission tests live in
test_close_preloads_emit_shared.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _bases import _PLUGIN_ROOT

# Commit 4: auto-merge override lives in mode-specific SKILL.md files,
# NOT in the shared file (per plan-reviewer concern fdcf62462321 —
# asymmetric mode logic should not pollute the shared file all 4
# skills consume).
_AUTO_MERGE_SKILL_MDS = {
    "story": _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
}
_NO_AUTO_MERGE_SKILL_MDS = {
    "sprint": _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md",
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
}


class TestStoryFreeAutoMergeOverride(unittest.TestCase):
    """Commit 4: story-close + free-close add a Step 6 override that
    auto-merges when (no Step 5c ask-user items queued) AND (no Block)
    AND (automated tests green). Sprint-close + plan-close do NOT —
    those are terminal merges into primary with bigger blast radius
    where the user expects to confirm.

    Per plan-reviewer concern ecc57a98b410: gating on green automated
    tests (deterministic, like v2.37.4 xp-accept) — not just LLM
    judgment from Step 5c — is what makes the auto-merge safe for the
    free-close primary-merge case.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.auto_merge_text = {
            mode: path.read_text() for mode, path in _AUTO_MERGE_SKILL_MDS.items()
        }
        cls.no_auto_merge_text = {
            mode: path.read_text() for mode, path in _NO_AUTO_MERGE_SKILL_MDS.items()
        }

    def test_story_free_skills_carry_auto_merge_override(self):
        # Pin the structural marker, not the literal keyword: the override
        # section opens with `override for Step 6 (auto-merge gate)` in both
        # story+free SKILL.md. Sprint+plan close test the absence of the
        # same marker (test_sprint_plan_skills_lack_auto_merge_override),
        # so a header rename cannot silently pass both halves.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "override for Step 6 (auto-merge gate)",
                    text,
                    f"{mode}-close SKILL.md must add an auto-merge "
                    f"override section (commit 4)",
                )

    def test_story_free_auto_merge_gates_on_tests_green(self):
        # Per concern ecc57a98b410: auto-merge must require deterministic
        # green-tests signal, not just LLM judgment from Step 5c. Pin
        # the gate so a future edit can't drop the deterministic check
        # and silently widen the blast radius.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                lower = self.auto_merge_text[mode].lower()
                self.assertIn(
                    "tests",
                    lower,
                    f"{mode}-close auto-merge override must mention tests",
                )
                self.assertIn(
                    "green",
                    lower,
                    f"{mode}-close auto-merge override must require green tests",
                )

    def test_story_free_auto_merge_uses_test_command_var_not_hardcoded_runner(
        self,
    ):
        # Per concern e343377dab19: the plugin ships to repos that may
        # use any test runner (pytest, npm, cargo, mix, …) or none.
        # The auto-merge gate must read TEST_COMMAND from the preload
        # (sourced from system_context.stack.test_command), NOT
        # hardcode `pytest -n auto`. Pin both halves so a future edit
        # can't silently revert to a project-specific runner name.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "TEST_COMMAND",
                    text,
                    f"{mode}-close auto-merge override must reference "
                    f"TEST_COMMAND env var (sourced from "
                    f"system_context.stack.test_command)",
                )
                self.assertNotIn(
                    "pytest",
                    text.lower(),
                    f"{mode}-close auto-merge override must not hardcode "
                    f"`pytest` — the plugin is project-generic; the test "
                    f"runner comes from TEST_COMMAND",
                )

    def test_story_free_auto_merge_surfaces_discovery_hint_when_unset(self):
        # Per plan-reviewer concern 4246adeaa521 + concern e343377dab19's
        # hint-discoverability requirement: when TEST_COMMAND is empty,
        # the override must NOT silently fall through — it must print a
        # discoverable nudge naming the WHAT to set
        # (system_context.stack.test_command) AND the actionable CLI
        # invocation (edit-stack-field). Otherwise a plugin user in
        # another repo never knows why auto-merge isn't firing.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "stack.test_command",
                    text,
                    f"{mode}-close override must name "
                    f"`stack.test_command` so the user knows WHAT to set",
                )
                self.assertIn(
                    "edit-stack-field",
                    text,
                    f"{mode}-close override must reference the "
                    f"`edit-stack-field` CLI subcommand so the user has "
                    f"a runnable invocation to enable the gate",
                )

    def test_story_free_auto_merge_uses_count_classifications_not_grep(self):
        # Per concern cd3b361020ca: the verification recipe for
        # condition 1 must use the structured count-classifications
        # CLI (filtering on metadata.action + route + ts), NOT a
        # grep over event content. Pin both halves: the new CLI is
        # mentioned, AND the legacy grep recipe is gone.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "count-classifications",
                    text,
                    f"{mode}-close auto-merge override must invoke the "
                    f"`count-classifications` CLI subcommand for "
                    f"structured verification",
                )
                self.assertIn(
                    "--route ask",
                    text,
                    f"{mode}-close override must filter the count to "
                    f"--route ask (the auto-merge gate cares about "
                    f"ask-routed items, not fix-routed)",
                )
                self.assertIn(
                    "CLOSE_START_TS",
                    text,
                    f"{mode}-close override must scope the count to events "
                    f"since CLOSE_START_TS (from the preload) so prior "
                    f"close cycles' classifications don't leak in",
                )
                self.assertNotIn(
                    "grep 'concern-classify",
                    text,
                    f"{mode}-close override must NOT grep event content "
                    f"prefix anymore — count-classifications is the "
                    f"canonical structured replacement",
                )

    def test_sprint_plan_skills_lack_auto_merge_override(self):
        # Sprint+plan close into primary as terminal merges. The user
        # confirms there. Auto-merge in those modes would be a
        # behavior regression.
        #
        # Test the structural marker, not the literal word: the
        # override section in story/free-close opens with the exact
        # header `override for Step 6 (auto-merge gate)`. Sprint+plan
        # close are free to mention "auto-merge" in prose explaining
        # the absence (per concern a4e03dbeefcb) — what they must not
        # carry is the override section itself.
        for mode in _NO_AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.no_auto_merge_text[mode]
                self.assertNotIn(
                    "override for Step 6 (auto-merge gate)",
                    text,
                    f"{mode}-close SKILL.md must NOT carry an auto-merge "
                    f"override section — terminal merges keep explicit confirm",
                )

    def test_free_close_auto_merge_blocks_on_design_decision(self):
        # Per concern 28f5e1b919d6: free-close merges to primary, so
        # any design_decision finding deserves a human checkpoint —
        # even if the Step 5c classifier routed it to `fix`. Pin both
        # the CLI invocation (--category design_decision) and the
        # numeric guard so a future edit can't silently drop the check.
        free_text = self.auto_merge_text["free"]
        self.assertIn(
            "--category design_decision",
            free_text,
            "free-close auto-merge must invoke count-classifications "
            "with --category design_decision (concern 28f5e1b919d6)",
        )
        self.assertIn(
            "DESIGN_DECISION_COUNT",
            free_text,
            "free-close auto-merge must capture DESIGN_DECISION_COUNT "
            "and gate on it (concern 28f5e1b919d6)",
        )

    def test_story_free_auto_merge_uses_cycle_id(self):
        # Per concern 1cf66a58205d: since-ts is time-scoped, not
        # cycle-scoped — concurrent close-cycles in other teammate
        # worktrees could leak concern_classify events into this
        # cycle's count. The auto-merge gate must invoke
        # count-classifications with --cycle-id <CLOSE_CYCLE_ID> so
        # the close_cycle_id metadata field strict-scopes the count.
        # --since-ts stays as belt-and-suspenders defense.
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                text = self.auto_merge_text[mode]
                self.assertIn(
                    "--cycle-id <CLOSE_CYCLE_ID>",
                    text,
                    f"{mode}-close auto-merge must invoke "
                    f"count-classifications with --cycle-id "
                    f"<CLOSE_CYCLE_ID> (concern 1cf66a58205d)",
                )

    def test_story_close_auto_merge_lacks_design_decision_guard(self):
        # Story-close merges into the sprint branch (not primary), so
        # the design_decision guard isn't load-bearing there — sprint+plan
        # close pick up the human checkpoint at the next boundary. Pin
        # the absence so a future copy-paste from free-close doesn't
        # silently widen the guard's blast radius.
        story_text = self.auto_merge_text["story"]
        self.assertNotIn(
            "--category design_decision",
            story_text,
            "story-close auto-merge must NOT carry the design_decision "
            "guard — that's free-close-only (merges to primary)",
        )


if __name__ == "__main__":
    unittest.main()
