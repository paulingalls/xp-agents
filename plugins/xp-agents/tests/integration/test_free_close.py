#!/usr/bin/env python3
"""Integration tests for the /xp-free-close skill.

Mirrors test_plan_close.py — six preload fields, TARGET_BRANCH resolves
to the primary integration branch (free-close merges a free branch into
primary, same as plan-close). The close-reviewer agent's `### free`
section already exists; this skill's job is to fork it.
"""

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


class TestFreeClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_as_primary(self):
        # Free-close merges a free branch into primary — use get-primary,
        # not get-target (free branches aren't plan branches and shouldn't
        # be misrouted by recorded plan branch lookup).
        write_system_context(self.smm_dir, stage=2)
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
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


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md"


class TestFreeCloseSkillText(unittest.TestCase):
    """SKILL.md body locks the free-close orchestration contract.

    Mirrors TestPlanCloseSkillText guard-tests — text-presence is the
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
        # Free-close from the primary branch is nonsensical — refuse.
        self.assertIn("CURRENT_BRANCH == TARGET_BRANCH", self.text)
        lower = self.text.lower()
        self.assertTrue(
            "refuse" in lower or "abort" in lower or "stop" in lower,
            "SKILL.md must describe refusing when CURRENT_BRANCH==TARGET_BRANCH",
        )

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
        # Mode must be 'free' for this skill.
        self.assertIn('"free"', self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_merge_branch_called_with_explicit_target(self):
        self.assertIn("merge-branch", self.text)
        self.assertIn("--target", self.text)
        self.assertIn("--branch", self.text)

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


if __name__ == "__main__":
    unittest.main()
