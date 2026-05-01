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


if __name__ == "__main__":
    unittest.main()
