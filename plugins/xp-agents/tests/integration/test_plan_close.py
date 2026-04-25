#!/usr/bin/env python3
"""Integration tests for the /xp-plan-close skill (sprint-033 story-001).

Mirrors test_sprint_close.py — six preload fields, but TARGET_BRANCH
resolves to the primary integration branch (plan-close merges plan
into primary, not into another plan).
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-plan-close" / "scripts" / "preload.sh"


class TestPlanClosePreload(_IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    def setUp(self):
        super().setUp()
        self.assertTrue(_PRELOAD.is_file(), f"Preload script missing: {_PRELOAD}")

    def _preload(self) -> subprocess.CompletedProcess:
        return self._run_preload(_PRELOAD)

    def test_emits_smm_dir(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "SMM_DIR"), str(self.smm_dir)
        )

    def test_emits_current_branch(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        actual_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(
            _extract_preload_var(result.stdout, "CURRENT_BRANCH"), actual_branch
        )

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

    def test_emits_gh_available_boolean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        gh = _extract_preload_var(result.stdout, "GH_AVAILABLE")
        self.assertIn(gh, ("true", "false"))

    def test_emits_worktree_clean_true_on_clean(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "true")

    def test_emits_worktree_clean_false_when_dirty(self):
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "false")

    def test_emits_review_input_path(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        review_input = _extract_preload_var(result.stdout, "REVIEW_INPUT")
        self.assertIsNotNone(review_input)
        review_path = Path(review_input)
        self.assertEqual(review_path.parent, self.smm_dir)
        self.assertTrue(review_path.name.startswith(".close-review-input."))
        self.assertTrue(review_path.exists(), "mktemp should create the file")

    def test_review_input_path_is_unique_per_call(self):
        first = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        second = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        self.assertNotEqual(first, second)

    def test_exits_zero_with_unwritable_smm(self):
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                _PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in (
            "SMM_DIR",
            "CURRENT_BRANCH",
            "TARGET_BRANCH",
            "GH_AVAILABLE",
            "WORKTREE_CLEAN",
            "REVIEW_INPUT",
        ):
            self.assertIsNotNone(
                _extract_preload_var(result.stdout, key),
                f"Missing key in preload output: {key}",
            )


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


if __name__ == "__main__":
    unittest.main()
