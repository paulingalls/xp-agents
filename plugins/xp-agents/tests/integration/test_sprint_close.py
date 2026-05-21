#!/usr/bin/env python3
"""Integration tests for the /xp-sprint-close skill (sprint-032 story-003).

Slice A covers the preload contract; slice B will extend with SKILL.md
text assertions for the dirty-tree refusal, with-gh / without-gh paths,
and merge+cleanup sequencing.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    seed_plan,
    seed_sprint_with_stories,
    write_system_context,
)
from _close_fixtures import (
    _ClosePreloadCommonTests,
    _CloseSkillTextCommonTests,
    _Step4SecurityIncludeTests,
)
from conftest import _extract_preload_var, _IntegrationTestCase


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

    # [story-004] Removed test_consumes_accept_active_marker +
    # test_idempotent_when_marker_absent — the marker no longer exists
    # under close-then-done; sprint-close has no consume to perform.

    def _seed_verify_event(self, status: str) -> None:
        # seed_sprint_with_stories writes sprint_id="sprint-001"; the verify
        # event must carry the same id for --query-verify-status to find it.
        seed_sprint_with_stories(self.smm_dir, [("story-001", "done")])
        meta: dict[str, object] = {
            "sprint_id": "sprint-001",
            "action": "verify",
            "verify_status": status,
        }
        if status == "red":
            meta["failing"] = [
                {"story": "story-001", "command": "false", "returncode": 1}
            ]
        result = self._run_append(
            "--type",
            "sprint",
            "--agent",
            "xp-test",
            "--content",
            "Sprint verify",
            "--metadata",
            json.dumps(meta),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_emits_verify_status_red_from_last_verify_event(self):
        self._seed_verify_event("red")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_STATUS"), "red")

    def test_emits_verify_status_green_when_last_event_green(self):
        self._seed_verify_event("green")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_STATUS"), "green")

    def test_emits_verify_status_none_when_no_verify_event(self):
        seed_sprint_with_stories(self.smm_dir, [("story-001", "done")])
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "VERIFY_STATUS"), "none")


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md"


class TestSprintCloseVerifyGate(unittest.TestCase):
    """story-003: SKILL.md gates the merge on the verify-acceptance status."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.text_lower = cls.text.lower()

    def test_skill_reads_verify_status_preload_var(self):
        self.assertIn(
            "VERIFY_STATUS",
            self.text,
            "sprint-close SKILL.md must read the preload's VERIFY_STATUS var",
        )

    def test_skill_refuses_merge_on_red(self):
        # Pin the gate: a red verify status must refuse/block the merge.
        self.assertIn("red", self.text_lower)
        refuse_tokens = ("refuse", "block", "stop", "do not merge", "abort")
        self.assertTrue(
            any(tok in self.text_lower for tok in refuse_tokens),
            "sprint-close SKILL.md must direct refusing the merge when "
            f"VERIFY_STATUS is red — none of {refuse_tokens} found",
        )

    def test_skill_force_close_escape_emits_debt(self):
        self.assertIn(
            "--force-close",
            self.text,
            "sprint-close SKILL.md must document the --force-close <reason> "
            "override for a red verify status",
        )
        self.assertIn(
            "debt",
            self.text_lower,
            "sprint-close SKILL.md must direct recording a debt event when "
            "--force-close bypasses a red verify gate",
        )


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

    # Sprint-close's preload uses get-merge-target, which returns a plan
    # branch (or primary) — never the sprint branch itself. The
    # same-branch case the mixin's test_refuses_when_current_equals_target
    # asserts is not reachable here, so opt out.
    _ASSERT_REFUSES_SAME_BRANCH = False

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
        merge_match = re.search(r"close_common\.py\s+merge", self.text)
        assert merge_match is not None
        chain_idx = self.text.index("/xp-plan-close")
        self.assertLess(
            merge_match.start(),
            chain_idx,
            "/xp-plan-close invocation must appear AFTER close_common.py merge",
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


class TestSprintCloseStep4(_Step4SecurityIncludeTests, _IntegrationTestCase):
    """Step 4 (Security Review) wired into xp-sprint-close."""

    _SKILL_MD = _SKILL_MD
    _MODE = "sprint"
    _SKILL_NAME = "xp-sprint-close"


if __name__ == "__main__":
    unittest.main()
