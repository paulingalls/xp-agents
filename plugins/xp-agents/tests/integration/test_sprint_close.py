#!/usr/bin/env python3
"""Integration tests for the /xp-sprint-close skill (sprint-032 story-003).

Slice A covers the preload contract; slice B will extend with SKILL.md
text assertions for the dirty-tree refusal, with-gh / without-gh paths,
and merge+cleanup sequencing.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import seed_plan, write_system_context
from _close_fixtures import _ClosePreloadCommonTests
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


class TestSprintCloseSkillText(unittest.TestCase):
    """Slice B: SKILL.md body locks the orchestration contract.

    These tests are guard-tests over markdown text — the practical
    ceiling for an LLM-read inline skill (no harness exercises the
    actual agent behavior). They pin the surfaces a future edit could
    silently break: dirty-tree refusal, with-gh + without-gh paths,
    review-input write, close-reviewer fork, merge+delete sequencing.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_refuses_when_worktree_clean_false(self):
        # The body must describe the refusal path when WORKTREE_CLEAN=false.
        self.assertIn("WORKTREE_CLEAN", self.text)
        lower = self.text.lower()
        self.assertTrue(
            "refuse" in lower or "abort" in lower or "stop" in lower,
            "SKILL.md must describe refusing/aborting on dirty worktree",
        )

    def test_gh_pr_create_only_inside_gh_available_branch(self):
        # `gh pr create` must appear inside a GH_AVAILABLE=true conditional
        # branch — not just somewhere in the file. Look for an explicit
        # `GH_AVAILABLE=true` near (within 200 chars before) the gh call.
        self.assertIn("gh pr create", self.text)
        gh_idx = self.text.index("gh pr create")
        prelude = self.text[max(0, gh_idx - 200) : gh_idx]
        self.assertRegex(
            prelude,
            r"GH_AVAILABLE\s*=\s*true",
            "gh pr create must be guarded by an explicit "
            "`GH_AVAILABLE=true` conditional within 200 chars before it",
        )

    def test_documents_no_gh_skip_path(self):
        # When GH_AVAILABLE=false the skill must describe what is skipped
        # so the operator knows the PR step was intentionally bypassed.
        lower = self.text.lower()
        self.assertTrue(
            "skip" in lower and ("gh" in lower or "pr" in lower),
            "SKILL.md must describe the gh-not-available skip path",
        )

    def test_writes_close_review_input_with_required_fields(self):
        # The body must instruct writing the close-review-input file with
        # the four keys the close-reviewer agent reads.
        self.assertIn("REVIEW_INPUT", self.text)
        for key in ("mode", "source_branch", "target_branch", "diff_command"):
            self.assertIn(key, self.text, f"Missing review-input key: {key}")

    def test_agent_prompt_carries_smm_dir_and_review_input(self):
        # The Agent prompt must literally embed SMM_DIR= and REVIEW_INPUT=
        # lines — the close-reviewer reads them from the prompt now that
        # SubagentStart no longer injects them. A heredoc reformat must
        # not silently drop these without breaking this guard.
        self.assertIn("SMM_DIR=", self.text)
        self.assertIn("REVIEW_INPUT=", self.text)
        # Mode must be 'sprint' for this skill.
        self.assertIn('"sprint"', self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        # The body must instruct forking xp-close-reviewer via the Agent tool.
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_merge_branch_called_with_explicit_target(self):
        # The body must invoke `branching.py merge-branch` with an
        # explicit --target — branching.py requires it and implicit
        # defaults caused drift in earlier iterations.
        self.assertIn("merge-branch", self.text)
        self.assertIn("--target", self.text)
        self.assertIn("--branch", self.text)

    def test_delete_branch_only_after_merge(self):
        # The body must invoke `branching.py delete ... --branch` AND that
        # call must appear AFTER the merge-branch call so cleanup never
        # runs on a failed merge. The CLI requires --cwd between them.
        delete_match = re.search(r"\bdelete\b.*--branch", self.text)
        assert delete_match is not None, "branching.py delete --branch not found"
        merge_idx = self.text.index("merge-branch")
        self.assertLess(
            merge_idx,
            delete_match.start(),
            "delete --branch must appear AFTER merge-branch",
        )

    def test_asks_user_before_merging(self):
        # Per design, the close skill must ask the user to confirm the
        # merge after presenting the reviewer's findings.
        self.assertIn("AskUserQuestion", self.text)

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
