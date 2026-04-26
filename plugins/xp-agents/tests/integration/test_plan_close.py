#!/usr/bin/env python3
"""Integration tests for the /xp-plan-close skill (sprint-033 story-001).

Mirrors test_sprint_close.py — six preload fields, but TARGET_BRANCH
resolves to the primary integration branch (plan-close merges plan
into primary, not into another plan).
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

from _branching_fixtures import write_system_context
from _close_fixtures import _ClosePreloadCommonTests
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent


class TestPlanClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_as_primary(self):
        # Plan-close always merges plan branch into primary — not into the
        # plan branch itself. Use get-primary, NOT get-target (which would
        # return the plan branch when called from the plan branch).
        write_system_context(self.smm_dir, stage=2)
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        # check=True so a broken branching.py doesn't yield "" == "" false-green.
        primary = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "get-primary",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(primary, "", "branching.py get-primary must resolve")
        self.assertEqual(_extract_preload_var(result.stdout, "TARGET_BRANCH"), primary)


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "SKILL.md"


class TestPlanCloseSkillText(unittest.TestCase):
    """SKILL.md body locks the plan-close orchestration contract.

    Mirrors TestSprintCloseSkillText guard-tests — text-presence is the
    practical ceiling for an LLM-read inline skill.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_refuses_when_worktree_clean_false(self):
        self.assertIn("WORKTREE_CLEAN", self.text)
        lower = self.text.lower()
        self.assertTrue(
            "refuse" in lower or "abort" in lower or "stop" in lower,
            "SKILL.md must describe refusing/aborting on dirty worktree",
        )

    def test_refuses_when_current_equals_target(self):
        # Plan-close from the primary branch is nonsensical — refuse.
        self.assertIn("CURRENT_BRANCH", self.text)
        self.assertIn("TARGET_BRANCH", self.text)

    def test_gh_pr_create_only_inside_gh_available_branch(self):
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
        lower = self.text.lower()
        self.assertTrue(
            "skip" in lower and ("gh" in lower or "pr" in lower),
            "SKILL.md must describe the gh-not-available skip path",
        )

    def test_writes_close_review_input_with_required_fields(self):
        self.assertIn("REVIEW_INPUT", self.text)
        for key in ("mode", "source_branch", "target_branch", "diff_command"):
            self.assertIn(key, self.text, f"Missing review-input key: {key}")

    def test_agent_prompt_carries_smm_dir_and_review_input(self):
        # The Agent prompt must literally embed SMM_DIR= and REVIEW_INPUT=.
        self.assertIn("SMM_DIR=", self.text)
        self.assertIn("REVIEW_INPUT=", self.text)
        # Mode must be 'plan' for this skill.
        self.assertIn('"plan"', self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_merge_branch_called_with_explicit_target(self):
        self.assertIn("merge-branch", self.text)
        self.assertIn("--target", self.text)
        self.assertIn("--branch", self.text)

    def test_archives_plan_only_after_merge(self):
        # plan_cli.py archive must appear AFTER the merge-branch call so
        # the plan stays intact on a failed merge.
        self.assertIn("plan_cli.py", self.text)
        self.assertIn("archive", self.text)
        merge_idx = self.text.index("merge-branch")
        archive_match = re.search(r"plan_cli\.py[^\n]*archive", self.text)
        assert archive_match is not None, "plan_cli.py archive call not found"
        self.assertLess(
            merge_idx,
            archive_match.start(),
            "plan_cli.py archive must appear AFTER merge-branch",
        )

    def test_delete_branch_only_after_merge(self):
        delete_match = re.search(r"\bdelete\b.*--branch", self.text)
        assert delete_match is not None, "branching.py delete --branch not found"
        merge_idx = self.text.index("merge-branch")
        self.assertLess(
            merge_idx,
            delete_match.start(),
            "delete --branch must appear AFTER merge-branch",
        )

    def test_asks_user_before_merging(self):
        self.assertIn("AskUserQuestion", self.text)


_SPRINT_CLOSE_SKILL = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md"
_CLOSE_REVIEWER_AGENT = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"
_PLAN_CLI = _PLUGIN_ROOT / "smm" / "plan_cli.py"


class TestSprintCloseToPlanCloseChainIntegrity(unittest.TestCase):
    """Capstone scenario 1: sprint-close → plan-close chain is wired.

    Mirrors TestSprintReviewToCloseChainIntegrity in test_sprint_close_chain.py:
    proves every node the chain requires (plan-close skill + preload, the
    sprint-close chain gate, the close-reviewer agent in plan mode) is
    present and wired. Per-step contracts live elsewhere; this only
    proves the parts compose.
    """

    @classmethod
    def setUpClass(cls):
        cls.plan_close_text = _SKILL_MD.read_text()
        cls.sprint_close_text = _SPRINT_CLOSE_SKILL.read_text()
        cls.agent_text = _CLOSE_REVIEWER_AGENT.read_text()

    def test_plan_close_skill_and_preload_exist(self):
        self.assertTrue(
            _SKILL_MD.is_file(),
            "/xp-plan-close SKILL.md must exist for the chain to land",
        )
        self.assertTrue(
            TestPlanClosePreload._PRELOAD.is_file(),
            "/xp-plan-close preload.sh must exist (skill loader runs it)",
        )

    def test_sprint_close_invokes_plan_close(self):
        # Story-002 wires the chain at the tail of /xp-sprint-close.
        self.assertIn("/xp-plan-close", self.sprint_close_text)
        # Gate uses both plan_cli.py checks.
        self.assertIn("get-branch", self.sprint_close_text)
        self.assertIn("is-plan-complete", self.sprint_close_text)

    def test_plan_close_forks_close_reviewer_in_plan_mode(self):
        # plan-close SKILL.md must invoke xp-close-reviewer with mode=plan.
        self.assertIn("xp-agents:xp-close-reviewer", self.plan_close_text)
        self.assertIn('"plan"', self.plan_close_text)

    def test_close_reviewer_agent_supports_plan_mode(self):
        # Agent's mode-aware focus list must include plan as a distinct
        # mode token — not just any prose containing "plan" / "planning".
        self.assertTrue(_CLOSE_REVIEWER_AGENT.is_file())
        self.assertRegex(
            self.agent_text,
            r"###\s+plan\b",
            "xp-close-reviewer must declare a plan-mode focus section",
        )


class TestPlanMergeAndArchiveEndToEnd(_IntegrationTestCase):
    """Capstone scenario 2: real plan + delivered milestone + plan branch
    → merge_branch + plan_cli archive lands the merge commit on primary
    and moves the plan into plans/. Mirrors test_sprint_close_chain.py's
    TestMergeAndCleanupEndToEnd but at the plan-close layer.

    The fixture creates a real single-milestone plan marked delivered
    so plan_cli is-plan-complete exits 0 (the exact gate sprint-close's
    Step 9 keys off). No mocks — honest E2E against branching.py +
    plan_cli.py primitives the LLM-driven SKILL.md instructs.
    """

    def _run_plan_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_PLAN_CLI), "--smm-dir", str(self.smm_dir), *args],
            capture_output=True,
            text=True,
        )

    def test_full_pipeline_with_delivered_milestone(self):
        # Real fixture: a single-milestone plan that's been delivered,
        # plus a plan branch one commit ahead of primary.
        import branching
        from _branching_fixtures import (
            get_current_branch,
            get_head_sha,
            make_commit,
            write_system_context,
        )

        write_system_context(self.smm_dir, stage=2)
        primary = get_current_branch(str(self.tmpdir))
        primary_sha_before = get_head_sha(str(self.tmpdir))

        # Build the plan via plan_cli — same path the planning skill uses.
        plan_branch = "test/plan-capstone"
        plan_payload = {
            "title": "Capstone Plan",
            "sources": [],
            "overview": "ov",
            "branch": plan_branch,
            "milestones": [
                {
                    "number": 1,
                    "name": "Ship it",
                    "status": "delivered",
                    "delivered_sprint": "sprint-099",
                    "goal": "deliver the capstone",
                    "done": "all green",
                    "sources": "n/a",
                    "change_zones": [],
                    "impact_zones": [],
                    "design_details": "n/a",
                    "constraints": [],
                }
            ],
        }
        subprocess.run(
            [
                sys.executable,
                str(_PLAN_CLI),
                "--smm-dir",
                str(self.smm_dir),
                "create",
            ],
            input=json.dumps(plan_payload),
            capture_output=True,
            text=True,
            check=True,
        )

        # is-plan-complete must exit 0 against this real plan — the exact
        # gate sprint-close's Step 9 chain keys off.
        gate = self._run_plan_cli("is-plan-complete")
        self.assertEqual(
            gate.returncode,
            0,
            f"is-plan-complete must exit 0 for an all-delivered plan: {gate.stderr}",
        )

        # get-branch returns the recorded plan branch.
        gb = self._run_plan_cli("get-branch")
        self.assertEqual(gb.returncode, 0, gb.stderr)
        self.assertEqual(gb.stdout.strip(), plan_branch)

        # Plan branch one commit ahead of primary.
        plan_tip = make_commit(
            str(self.tmpdir),
            plan_branch,
            "plan-feature.txt",
            "delivered",
            "plan-only commit",
        )

        # ACT: merge the plan branch into primary, then archive the plan.
        # These are the two primitives /xp-plan-close orchestrates.
        branching.merge_branch(str(self.tmpdir), plan_branch, target=primary)
        archive = self._run_plan_cli("archive")
        self.assertEqual(archive.returncode, 0, archive.stderr)

        # ASSERT: primary HEAD is a --no-ff merge commit pointing at the
        # plan branch tip.
        self.assertEqual(get_current_branch(str(self.tmpdir)), primary)
        primary_head = get_head_sha(str(self.tmpdir))
        self.assertNotEqual(primary_head, primary_sha_before)
        parents = (
            subprocess.run(
                ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                cwd=self.tmpdir,
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .split()
        )
        self.assertEqual(
            len(parents),
            3,
            f"--no-ff merge must produce 2 parents, got: {parents}",
        )
        # First parent is the prior primary tip; second is the plan tip.
        self.assertEqual(parents[1], primary_sha_before)
        self.assertEqual(parents[2], plan_tip)

        # ASSERT: execution_plan.json is gone from SMM_DIR root and a
        # timestamped file exists under plans/.
        self.assertFalse(
            (self.smm_dir / "execution_plan.json").exists(),
            "execution_plan.json must be moved out of SMM root after archive",
        )
        plans_dir = self.smm_dir / "plans"
        self.assertTrue(plans_dir.is_dir())
        archived = list(plans_dir.glob("execution_plan_*.json"))
        self.assertEqual(
            len(archived),
            1,
            f"Expected one archived plan, got: {archived}",
        )


if __name__ == "__main__":
    unittest.main()
