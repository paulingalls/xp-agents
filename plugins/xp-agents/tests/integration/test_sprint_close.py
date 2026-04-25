#!/usr/bin/env python3
"""Integration tests for the /xp-sprint-close skill (sprint-032 story-003).

Slice A covers the preload contract; slice B will extend with SKILL.md
text assertions for the dirty-tree refusal, with-gh / without-gh paths,
and merge+cleanup sequencing.
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

from _branching_fixtures import seed_plan, write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"


class TestSprintClosePreload(_IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    def setUp(self):
        super().setUp()
        # Assert the script exists — no silent skipTest while we're red.
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
        # _IntegrationTestCase tearDown removes tmpdir, so no manual cleanup.
        (self.tmpdir / "dirty.txt").write_text("uncommitted")
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_extract_preload_var(result.stdout, "WORKTREE_CLEAN"), "false")

    def test_emits_review_input_path(self):
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        review_input = _extract_preload_var(result.stdout, "REVIEW_INPUT")
        self.assertEqual(review_input, str(self.smm_dir / ".close-review-input.json"))

    def test_exits_zero_with_unwritable_smm(self):
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its six lines (TARGET_BRANCH may be
        # empty when there is no plan) and exit 0.
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                _PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        # All six keys still present.
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
        # The body must instruct writing .close-review-input.json with
        # the four keys the close-reviewer agent reads (mode, source_branch,
        # target_branch, diff_command).
        self.assertIn(".close-review-input.json", self.text)
        for key in ("mode", "source_branch", "target_branch", "diff_command"):
            self.assertIn(key, self.text, f"Missing review-input key: {key}")
        # Mode must be 'sprint' for this skill.
        self.assertIn('"sprint"', self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        # The body must instruct forking xp-close-reviewer via the Agent tool.
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_merge_sprint_called_with_explicit_target(self):
        # The body must invoke `branching.py merge-sprint` with an
        # explicit --target — branching.py requires it and implicit
        # defaults caused drift in earlier iterations.
        self.assertIn("merge-sprint", self.text)
        self.assertIn("--target", self.text)
        self.assertIn("--branch", self.text)

    def test_delete_branch_only_after_merge(self):
        # The body must invoke `branching.py delete ... --branch` AND that
        # call must appear AFTER the merge-sprint call so cleanup never
        # runs on a failed merge. The CLI requires --cwd between them.
        delete_match = re.search(r"\bdelete\b.*--branch", self.text)
        assert delete_match is not None, "branching.py delete --branch not found"
        merge_idx = self.text.index("merge-sprint")
        self.assertLess(
            merge_idx,
            delete_match.start(),
            "delete --branch must appear AFTER merge-sprint",
        )

    def test_asks_user_before_merging(self):
        # Per design, the close skill must ask the user to confirm the
        # merge after presenting the reviewer's findings.
        self.assertIn("AskUserQuestion", self.text)


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
