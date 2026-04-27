#!/usr/bin/env python3
"""Integration tests for the /xp-sprint-close skill (sprint-032 story-003).

Slice A covers the preload contract; slice B will extend with SKILL.md
text assertions for the dirty-tree refusal, with-gh / without-gh paths,
and merge+cleanup sequencing.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import seed_plan, write_system_context
from _close_fixtures import _ClosePreloadCommonTests, _CloseSkillTextCommonTests
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent


class TestSprintClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_via_get_merge_target(self):
        # Stage 2 + recorded plan branch → TARGET_BRANCH = the plan branch.
        write_system_context(self.smm_dir, stage=2)
        seed_plan(self.smm_dir, branch="test/plan-feat")
        subprocess.run(
            ["git", "branch", "test/plan-feat"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "TARGET_BRANCH"), "test/plan-feat"
        )


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md"


class TestSprintCloseSkillText(_CloseSkillTextCommonTests, unittest.TestCase):
    """Sprint-close SKILL.md guard tests.

    Inherits the shared close-skill guards from
    _CloseSkillTextCommonTests (refusal prose, gh-conditional, prompt-section
    contract for the close-reviewer, agent prompt literals, merge+delete
    ordering, AskUserQuestion).  Adds the sprint-specific plan-close chain
    test.
    """

    _SKILL_MD = _SKILL_MD
    _MODE = "sprint"

    def test_invokes_plan_close_when_plan_complete(self):
        # After a successful merge, the skill must check whether the
        # current plan is complete (all milestones delivered/deferred)
        # and a plan branch is recorded — if so, chain into /xp-plan-close.
        self.assertIn("plan_cli.py", self.text)
        self.assertIn("get-branch", self.text)
        self.assertIn("is-plan-complete", self.text)
        self.assertIn("/xp-plan-close", self.text)
        # The chain step must appear AFTER the merge — not before — so a
        # failed merge does not trigger plan-close.
        merge_idx = self.text.index("merge-branch")
        chain_idx = self.text.index("/xp-plan-close")
        self.assertLess(
            merge_idx,
            chain_idx,
            "/xp-plan-close invocation must appear AFTER merge-branch",
        )


_SPRINT_REVIEW_SKILL = _PLUGIN_ROOT / "skills" / "xp-sprint-review" / "SKILL.md"


class TestSprintReviewChainsToClose(unittest.TestCase):
    """story-004: xp-sprint-review SKILL.md tells main agent to invoke close.

    The chain is fragile if it lives only in the agent's head — pin it
    to the SKILL.md text so a future skill edit can't silently drop it.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SPRINT_REVIEW_SKILL.read_text()

    def test_references_xp_sprint_close(self):
        # The skill body must mention /xp-sprint-close so the main agent
        # knows to invoke it after surfacing findings.
        self.assertIn("/xp-sprint-close", self.text)

    def test_chain_instruction_appears_after_main_agent_block(self):
        # The chain instruction should follow the existing
        # "If you are the main agent" block (the natural insertion point).
        main_agent_idx = self.text.index("If you are the main agent")
        close_idx = self.text.index("/xp-sprint-close")
        self.assertLess(
            main_agent_idx,
            close_idx,
            "/xp-sprint-close instruction should follow the main-agent block",
        )


if __name__ == "__main__":
    unittest.main()
