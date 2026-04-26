#!/usr/bin/env python3
"""Shared test fixtures for the close-skill family preload tests.

`_ClosePreloadCommonTests` covers the eight assertions every close-skill
preload must satisfy: it emits SMM_DIR, CURRENT_BRANCH, GH_AVAILABLE,
WORKTREE_CLEAN, REVIEW_INPUT (mktemp, unique per call), and exits 0
even with a fresh CLAUDE_PLUGIN_DATA. Subclasses inherit the mixin
plus `_IntegrationTestCase` and supply `_PRELOAD`. The TARGET_BRANCH
assertion is skill-specific (sprint-close uses get-target, plan-close
uses get-primary, free-close will mirror plan-close), so subclasses
own that test individually.

`_CloseSkillTextCommonTests` covers the nine SKILL.md guard assertions
shared across sprint/plan/free close skills (refusal prose, gh-conditional
PR, REVIEW_INPUT keys, agent prompt literals, merge+delete ordering, etc.).
Subclasses supply `_SKILL_MD: Path` and `_MODE: str` ("sprint" | "plan" |
"free"); mode-specific tests (plan-archive, sprint→plan-close chain,
current==target refusal) stay on the subclasses.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import marker_names
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

    def test_emits_review_input_path(self):
        # REVIEW_INPUT is a per-invocation tempfile under SMM_DIR — concurrent
        # close skills in different worktrees must not race on a shared path.
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        review_input = _extract_preload_var(result.stdout, "REVIEW_INPUT")
        self.assertIsNotNone(review_input)
        review_path = Path(review_input)
        self.assertEqual(review_path.parent, self.smm_dir)
        self.assertTrue(
            review_path.name.startswith(marker_names.CLOSE_REVIEW_INPUT_PREFIX)
        )
        self.assertTrue(review_path.exists(), "mktemp should create the file")

    def test_review_input_path_is_unique_per_call(self):
        first = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        second = _extract_preload_var(self._preload().stdout, "REVIEW_INPUT")
        self.assertNotEqual(first, second)

    def test_exits_zero_with_unwritable_smm(self):
        # Override CLAUDE_PLUGIN_DATA to a fresh empty dir so init.sh
        # produces a different SMM path with no shared_mental_model.json.
        # Preload should still emit its six lines and exit 0.
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
            "REVIEW_INPUT",
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

    def test_writes_close_review_input_with_required_fields(self):
        # The body must instruct writing the close-review-input file with
        # the four keys the close-reviewer agent reads.
        self.assertIn("REVIEW_INPUT", self.text)
        for key in ("mode", "source_branch", "target_branch", "diff_command"):
            self.assertIn(key, self.text, f"Missing review-input key: {key}")

    def test_agent_prompt_carries_smm_dir_and_review_input(self):
        # The Agent prompt must literally embed SMM_DIR= and REVIEW_INPUT=
        # lines — the close-reviewer reads them from the prompt now that
        # SubagentStart no longer injects them. Mode literal must match.
        self.assertIn("SMM_DIR=", self.text)
        self.assertIn("REVIEW_INPUT=", self.text)
        self.assertIn(f'"{self._MODE}"', self.text)

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
