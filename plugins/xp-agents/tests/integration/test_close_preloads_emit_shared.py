#!/usr/bin/env python3
"""Each close-skill preload appends the shared close-pipeline reference.

After commit 2a of the spike-008 follow-up, all four close skills source
their Step 5 / 5b / 6 prose from a single file at
`scripts/_close_pipeline_shared.md`. Each preload `cat`s that file at the
end of its output so the LLM running the skill sees one consistent set of
shared instructions instead of four near-duplicate copies.

These tests assert the preload-side mechanic: when a close-skill preload
runs, its stdout contains the shared content's marker headings and key
phrases. Subsequent commits add Step 5c (commit 3) and tighten Step 6
(commit 4); those tests live alongside these and reuse the same fixture
pattern.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _close_fixtures import _ClosePreloadCommonTests
from conftest import _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent


class _SharedPreloadAssertions(_ClosePreloadCommonTests):
    """Mixin asserting the shared close-pipeline content appears in stdout.

    Subclasses extend this PLUS _IntegrationTestCase (same pattern as
    _ClosePreloadCommonTests). The assertions check for marker phrases
    that are present in `scripts/_close_pipeline_shared.md` from
    commit 2a onward — the heading and at least one phrase per
    extracted step (5, 5b, 6).
    """

    def test_emits_shared_pipeline_heading(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "## Shared close-pipeline reference",
            result.stdout,
            "preload must emit the shared close-pipeline heading",
        )

    def test_emits_step5_present_findings_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5: Present findings",
            result.stdout,
            "preload must emit Step 5 (Present findings) heading",
        )

    def test_emits_step5b_resolve_addressed_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5b: Resolve Addressed Concerns",
            result.stdout,
            "preload must emit Step 5b (Resolve Addressed Concerns) heading",
        )
        self.assertIn(
            "LIKELY ADDRESSED",
            result.stdout,
            "Step 5b body must mention the LIKELY ADDRESSED annotation",
        )

    def test_emits_step6_confirm_merge_marker(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 6: Confirm the merge",
            result.stdout,
            "preload must emit Step 6 (Confirm the merge) heading",
        )
        self.assertIn(
            "AskUserQuestion",
            result.stdout,
            "Step 6 body must mention AskUserQuestion (merge-confirm prompt)",
        )

    def test_emits_block_flip_default_paragraph(self):
        # Receiver-side honoring of the xp-close-reviewer Step 3.5 contract:
        # Block findings flip the merge default to Abort. Lives in shared
        # so all four close skills enforce it identically.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        lower = result.stdout.lower()
        self.assertIn(
            "block finding",
            lower,
            "Step 6 body must mention 'Block finding' for the Abort-default flip",
        )
        self.assertIn(
            "recommended",
            lower,
            "Step 6 body must instruct marking the Abort option '(Recommended)'",
        )

    def test_emits_step5c_classify_and_act_marker(self):
        # Commit 3: Step 5c — fix-or-ask classifier (spike-008 Path 2,
        # LLM-side, no Python regex). Each NEW concern/block from the
        # reviewer gets sorted into "fix it now" or "defer to user".
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "### Step 5c: Classify and act on reviewer findings",
            result.stdout,
            "preload must emit Step 5c (Classify and act) heading",
        )

    def test_emits_step5c_code_fixable_categories(self):
        # The seven Class-A/B categories the LLM should fix inline
        # (per spike-008 §3 vocabulary). Pin each so a future edit
        # that drops one fails loudly instead of silently routing the
        # dropped category to "ask user". subTest reports each missing
        # category individually rather than masking after the first.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for category in (
            "lint",
            "test_failure",
            "ac_coverage",
            "file_domain_drift",
            "honesty_gap",
            "file_split",
            "spec_drift",
        ):
            with self.subTest(category=category):
                self.assertIn(
                    f"`{category}`",
                    result.stdout,
                    f"Step 5c code-fixable bucket must list `{category}`",
                )

    def test_emits_step5c_ask_user_categories(self):
        # The three Class-C categories that require user judgment
        # (per spike-008 §3 vocabulary). subTest gives per-category
        # failure visibility, same as the code-fixable test above.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        for category in ("design_decision", "ac_amendment", "plan_discipline"):
            with self.subTest(category=category):
                self.assertIn(
                    f"`{category}`",
                    result.stdout,
                    f"Step 5c ask-user bucket must list `{category}`",
                )

    def test_emits_step5c_default_to_ask(self):
        # Safety: when the LLM can't classify, default to ASK rather
        # than silently auto-fixing something it doesn't understand.
        # Case-insensitive — markdown bolding may capitalize the leading
        # word; what matters is that the policy is stated.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "default to ask",
            result.stdout.lower(),
            "Step 5c must instruct default-to-ASK on uncertain classification",
        )

    def test_emits_step5c_resolves_event_trailer_hook(self):
        # Each LLM fix must commit with a Resolves-Event trailer so
        # the auto-link hook closes the concern. Without this guidance
        # the LLM might leave concerns open after fixing them.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Resolves-Event:",
            result.stdout,
            "Step 5c must instruct adding Resolves-Event: trailer to fix commits",
        )

    def test_emits_step5c_audit_trail_append_template(self):
        # Each classification appends a status event so retrospective
        # tooling can sample classifications to measure rule precision.
        # Pin the canonical content prefix + append.sh invocation. The
        # prefix must be plugin-generic (no spike-NNN names) since the
        # plugin ships to projects that have no notion of spike-008.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "concern-classify",
            result.stdout,
            "Step 5c audit trail must use the plugin-generic "
            "'concern-classify' status content prefix",
        )
        self.assertIn(
            "append.sh",
            result.stdout,
            "Step 5c audit trail must reference append.sh to record the event",
        )

    def test_step5c_does_not_leak_project_internal_refs(self):
        # The shared file ships to other projects; it must not mention
        # project-internal naming (spike numbers, sprint numbers, SMM
        # event hex IDs) that would be meaningless out-of-context.
        # Tests under tests/ and docs/ may freely reference spike-008
        # — those don't ship.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(
            "spike-008",
            result.stdout.lower(),
            "Shared close-pipeline content must not name 'spike-008' — "
            "the plugin ships to other projects",
        )


class TestStoryClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"


class TestSprintClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"


class TestPlanClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: plan-close preload now emits the shared content too.

    Step 5b previously skipped on the rationale that story+sprint close
    already auto-resolved everything resolvable. Multi-sprint plans
    break that assumption — concerns from sprint N can be LIKELY-
    ADDRESSED by commits in sprint N+1, but sprint N's close window has
    already passed when those commits land. Plan-close is the last
    chance to catch slipped-through matches.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"


class TestFreeClosePreloadEmitsShared(_SharedPreloadAssertions, _IntegrationTestCase):
    """Commit 2b: free-close preload now emits the shared content too.

    Step 5b previously skipped on the (incorrect) rationale that free
    branches don't carry sprint/plan-tracked concerns. Demonstrably
    wrong — free branches routinely fix tracked concerns when used for
    follow-up work (cleanup, docs, fixes). The triage_preload helper
    looks for files-touched overlap with open concerns and is mode-
    agnostic; nothing about free-mode justifies the skip.
    """

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"


_SKIP_NOTE_TARGETS = {
    "plan": _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md",
    "free": _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md",
}

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
_SHARED_CLOSE_PIPELINE = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"


class TestPlanFreeCloseSkillMDDropsSkipNote(unittest.TestCase):
    """Commit 2b removes the 'skip LIKELY ADDRESSED' notes from
    xp-plan-close + xp-free-close SKILL.md. The shared file's Step 5b
    now applies uniformly across all 4 close skills; leaving the skip
    notes inline would contradict the preload-injected guidance.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.skill_lower = {
            mode: path.read_text().lower() for mode, path in _SKIP_NOTE_TARGETS.items()
        }

    def test_close_skills_drop_skip_likely_addressed_note(self):
        for mode in _SKIP_NOTE_TARGETS:
            with self.subTest(mode=mode):
                self.assertNotIn(
                    "does not run the likely addressed",
                    self.skill_lower[mode],
                    f"{mode}-close SKILL.md must drop the 'skip LIKELY "
                    f"ADDRESSED' note in commit 2b — it now contradicts "
                    f"the shared Step 5b",
                )


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
        for mode in _AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                lower = self.auto_merge_text[mode].lower()
                self.assertIn(
                    "auto-merge",
                    lower,
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

    def test_sprint_plan_skills_lack_auto_merge_override(self):
        # Sprint+plan close into primary as terminal merges. The user
        # confirms there. Auto-merge in those modes would be a
        # behavior regression.
        for mode in _NO_AUTO_MERGE_SKILL_MDS:
            with self.subTest(mode=mode):
                lower = self.no_auto_merge_text[mode].lower()
                self.assertNotIn(
                    "auto-merge",
                    lower,
                    f"{mode}-close SKILL.md must NOT carry an auto-merge "
                    f"override — terminal merges keep explicit confirm",
                )


class TestSharedPipelineCoherence(unittest.TestCase):
    """Per plan-reviewer concern ee1db2bd2f8a: each preceding commit's
    smoke test only checks that commit's marker text. After commits 2,
    3, AND 4 land, the shared file's section ordering should still
    flow: Step 5 → Step 5b → Step 5c → Step 6. A scrambled or
    duplicated heading would break LLM execution but no per-commit
    smoke test would catch it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shared_text = _SHARED_CLOSE_PIPELINE.read_text()

    def test_step_headings_appear_in_expected_order(self):
        expected = [
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ]
        positions = [self.shared_text.find(heading) for heading in expected]
        for heading, pos in zip(expected, positions, strict=True):
            self.assertNotEqual(
                pos,
                -1,
                f"Shared close-pipeline file missing required heading: {heading}",
            )
        self.assertEqual(
            positions,
            sorted(positions),
            f"Shared close-pipeline headings out of order. "
            f"Expected {expected}; got positions {positions}",
        )

    def test_each_step_heading_appears_exactly_once(self):
        # Duplicate headings would confuse the LLM about which body
        # block to follow. Pin uniqueness alongside ordering.
        for heading in (
            "### Step 5: Present findings",
            "### Step 5b: Resolve Addressed Concerns",
            "### Step 5c: Classify and act on reviewer findings",
            "### Step 6: Confirm the merge",
        ):
            with self.subTest(heading=heading):
                self.assertEqual(
                    self.shared_text.count(heading),
                    1,
                    f"Heading must appear exactly once: {heading}",
                )


if __name__ == "__main__":
    unittest.main()
