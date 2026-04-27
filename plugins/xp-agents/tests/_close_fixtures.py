#!/usr/bin/env python3
"""Shared test fixtures for the close-skill family preload tests.

`_ClosePreloadCommonTests` covers the assertions every close-skill
preload must satisfy: it emits SMM_DIR, CURRENT_BRANCH, GH_AVAILABLE,
WORKTREE_CLEAN, and exits 0 even with a fresh CLAUDE_PLUGIN_DATA.
Subclasses inherit the mixin plus `_IntegrationTestCase` and supply
`_PRELOAD`. The TARGET_BRANCH assertion is skill-specific (sprint-close
uses get-target, plan-close uses get-primary, free-close mirrors
plan-close), so subclasses own that test individually.

`_CloseSkillTextCommonTests` covers the SKILL.md guard assertions
shared across sprint/plan/free close skills (refusal prose, gh-conditional
PR, prompt-section names for the close-reviewer, agent prompt literals,
merge+delete ordering, etc.). Subclasses supply `_SKILL_MD: Path` and
`_MODE: str` ("sprint" | "plan" | "free"); mode-specific tests
(plan-archive, sprint→plan-close chain, current==target refusal) stay
on the subclasses.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from conftest import _extract_preload_var


class _ClosePreloadCommonTests:
    """Mixin asserting the shared preload contract.

    Subclasses must define:
        _PRELOAD: Path — absolute path to the preload.sh under test.
    """

    _PRELOAD: Path

    def setUp(self) -> None:
        super().setUp()
        # Assert the script exists — no silent skipTest while we're red.
        self.assertTrue(
            self._PRELOAD.is_file(), f"Preload script missing: {self._PRELOAD}"
        )

    def _preload(self) -> subprocess.CompletedProcess:
        return self._run_preload(self._PRELOAD)

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

    def test_does_not_emit_review_input(self):
        # The close skill no longer creates a tempfile or echoes a
        # REVIEW_INPUT line — the four close-review fields are now passed
        # inline in the Agent prompt as ## Source Branch / Target Branch /
        # Diff Command sections, with the mode literal already in the prompt.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(
            _extract_preload_var(result.stdout, "REVIEW_INPUT"),
            "preload must not emit REVIEW_INPUT (file pattern removed)",
        )

    def test_exits_zero_with_unwritable_smm(self):
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its five lines and exit 0.
        with tempfile.TemporaryDirectory() as fresh_data:
            result = self._run_preload(
                self._PRELOAD, extra_env={"CLAUDE_PLUGIN_DATA": fresh_data}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in (
            "SMM_DIR",
            "CURRENT_BRANCH",
            "TARGET_BRANCH",
            "GH_AVAILABLE",
            "WORKTREE_CLEAN",
        ):
            self.assertIsNotNone(
                _extract_preload_var(result.stdout, key),
                f"Missing key in preload output: {key}",
            )


class _CloseSkillTextCommonTests:
    """Mixin asserting the shared SKILL.md guard contract.

    Subclasses must define:
        _SKILL_MD: Path — absolute path to the close skill's SKILL.md
        _MODE: str    — "sprint" | "plan" | "free"; used by the
                        Agent-prompt-mode assertion.

    Mode-specific tests (current==target refusal for plan/free,
    plan_cli archive for plan, /xp-plan-close chain for sprint) live
    on the subclasses — not enough overlap to justify another mixin.
    """

    _SKILL_MD: Path
    _MODE: str

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.text = cls._SKILL_MD.read_text()

    def test_refuses_when_worktree_clean_false(self):
        # The body must describe the refusal path when WORKTREE_CLEAN=false.
        self.assertIn("WORKTREE_CLEAN", self.text)
        lower = self.text.lower()
        self.assertTrue(
            "refuse" in lower or "abort" in lower or "stop" in lower,
            "SKILL.md must describe refusing/aborting on dirty worktree",
        )

    def test_gh_pr_create_only_inside_gh_available_branch(self):
        # `gh pr create` must appear inside a GH_AVAILABLE=true conditional —
        # not just somewhere in the file. Look for an explicit
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

    def test_prompt_template_carries_close_review_fields(self):
        # The Agent prompt template must include the four close-review
        # sections inline — the close-reviewer reads them from the prompt
        # now that the JSON file pattern was removed. The mode literal
        # ('sprint' | 'plan' | 'free') must also appear in the prompt.
        self.assertNotIn(
            "REVIEW_INPUT",
            self.text,
            "REVIEW_INPUT pattern was removed; SKILL.md must not reference it",
        )
        for section in (
            "## Mode",
            "## Source Branch",
            "## Target Branch",
            "## Diff Command",
        ):
            self.assertIn(
                section, self.text, f"Missing prompt section heading: {section}"
            )

    def test_agent_prompt_carries_smm_dir_and_mode(self):
        # The Agent prompt must literally embed SMM_DIR= and the mode
        # literal under the ## Mode section — the close-reviewer reads
        # them from the prompt now that SubagentStart no longer injects
        # anything for it.
        self.assertIn("SMM_DIR=", self.text)
        self.assertIn(f"## Mode\\n{self._MODE}", self.text)

    def test_invokes_close_reviewer_via_agent_tool(self):
        # The body must instruct forking xp-close-reviewer via the Agent tool.
        self.assertIn("xp-agents:xp-close-reviewer", self.text)
        self.assertIn("subagent_type", self.text)

    def test_merge_branch_called_with_explicit_target(self):
        # The body must invoke `branching.py merge-branch` with an explicit
        # --target — branching.py requires it and implicit defaults caused
        # drift in earlier iterations.
        self.assertIn("merge-branch", self.text)
        self.assertIn("--target", self.text)
        self.assertIn("--branch", self.text)

    def test_delete_branch_only_after_merge(self):
        # The body must invoke `branching.py delete ... --branch` AND that
        # call must appear AFTER the merge-branch call so cleanup never
        # runs on a failed merge.
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
