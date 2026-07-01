#!/usr/bin/env python3
"""Tests for branching.py — pure-function unit tests.

Covers: branch_name, sprint_branch_name, get_branching_stage,
is_protected_branch, is_sprint_branch.

Commit message parsing tests (extract_commit_message,
is_escape_hatch_commit) are in test_commits.py.

Git-operation lifecycle tests (create, merge, delete, CLI) are in
test_branching_lifecycle.py.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching
import execution_plan_store
from _branching_fixtures import write_system_context
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase
from event_schema import EVENT_TYPE_DECISION


class TestBranchLifecycleShimImports(unittest.TestCase):
    """Catch cascade failure in <1s when branch_lifecycle extraction
    breaks the backwards-compat re-exports — per wisdom ab40b12643ab,
    a one-line shim-import test fails fast instead of waiting for
    80 downstream tests to red.
    """

    def test_lifecycle_symbols_resolve_via_branching(self):
        from branching import (
            _fast_forward_if_safe,
            _is_merged_into,
            _merge_into_target,
            delete_branch,
            merge_branch,
        )

        for fn in (
            delete_branch,
            merge_branch,
            _is_merged_into,
            _fast_forward_if_safe,
            _merge_into_target,
        ):
            self.assertTrue(callable(fn))


class TestBranchName(unittest.TestCase):
    def test_basic_format(self):
        result = branching.branch_name("paul", "story-001", "schema-validation")
        self.assertEqual(result, "paul/story-001-schema-validation")

    def test_slug_sanitization(self):
        result = branching.branch_name("paul", "story-002", "Add Feature!!!")
        self.assertEqual(result, "paul/story-002-add-feature")

    def test_uppercase_lowered(self):
        result = branching.branch_name("Paul", "story-003", "CLI")
        self.assertEqual(result, "Paul/story-003-cli")

    def test_empty_slug(self):
        result = branching.branch_name("paul", "story-004", "---")
        self.assertEqual(result, "paul/story-004-")


class TestGetBranchingStage(unittest.TestCase):
    def test_no_system_context_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)

    def test_no_branching_strategy_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "system_context.json").write_text(
                json.dumps({"project_name": "test"})
            )
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)

    def test_returns_declared_stage(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "project_name": "test",
                "branching_strategy": {"stage": 2},
            }
            (Path(td) / "system_context.json").write_text(json.dumps(ctx))
            self.assertEqual(branching.get_branching_stage(Path(td)), 2)

    def test_stage_zero_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "project_name": "test",
                "branching_strategy": {"stage": 0},
            }
            (Path(td) / "system_context.json").write_text(json.dumps(ctx))
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)


class TestBranchMinStage(unittest.TestCase):
    """All branch types require Stage 2+ — Stage 1 is dead code under
    auto-promote (any read of the stage promotes 1 to 2 before it's
    observed). Keeping any threshold at 1 lies about the floor.
    """

    def test_all_thresholds_at_stage_2(self):
        self.assertEqual(
            branching.BRANCH_MIN_STAGE,
            {
                "story": 2,
                "sprint": 2,
                "plan": 2,
                "free": 2,
                "scaffold": 2,
            },
        )


class TestSprintBranchName(unittest.TestCase):
    def test_basic_format(self):
        result = branching.sprint_branch_name("paul", "sprint-027", "integration")
        self.assertEqual(result, "paul/sprint-027-integration")

    def test_slug_sanitization(self):
        result = branching.sprint_branch_name("paul", "sprint-027", "Stage 2 Flow!!")
        self.assertEqual(result, "paul/sprint-027-stage-2-flow")

    def test_sprint_id_preserved(self):
        result = branching.sprint_branch_name("alice", "sprint-001", "test")
        self.assertEqual(result, "alice/sprint-001-test")


class TestIsSprintBranch(unittest.TestCase):
    def test_valid_sprint_branch(self):
        self.assertTrue(branching.is_sprint_branch("paul/sprint-027-integration"))

    def test_story_branch_not_sprint(self):
        self.assertFalse(branching.is_sprint_branch("paul/story-001-feature"))

    def test_main_not_sprint(self):
        self.assertFalse(branching.is_sprint_branch("main"))

    def test_bare_sprint_prefix_not_sprint(self):
        self.assertFalse(branching.is_sprint_branch("sprint-027"))

    def test_empty_not_sprint(self):
        self.assertFalse(branching.is_sprint_branch(""))


class TestIsFreeBranch(unittest.TestCase):
    """Free branches follow `<user>/free-YYYY-MM-DD-<slug>` per free_branch_name.

    Mirrors TestIsSprintBranch: anchored regex match against the documented
    shape. Anything that deviates degrades silently to "not free", which is
    the safe-fail mode for retro_metrics' is_free_session filter (denominator-
    inclusive — over-counts, never under-tags real free work)."""

    def test_valid_free_branch(self):
        self.assertTrue(
            branching.is_free_branch("paulingalls/free-2026-05-23-rate-fix")
        )

    def test_valid_free_branch_short_user(self):
        self.assertTrue(branching.is_free_branch("paul/free-2026-04-24-spike-foo"))

    def test_story_branch_not_free(self):
        self.assertFalse(branching.is_free_branch("paul/story-007-demo"))

    def test_sprint_branch_not_free(self):
        self.assertFalse(branching.is_free_branch("paul/sprint-097-foo"))

    def test_main_not_free(self):
        self.assertFalse(branching.is_free_branch("main"))

    def test_bare_free_prefix_not_free(self):
        self.assertFalse(branching.is_free_branch("free-2026-05-23-foo"))

    def test_malformed_date_not_free(self):
        # 'not-a-date' replaces the YYYY-MM-DD segment.
        self.assertFalse(branching.is_free_branch("paul/free-not-a-date-slug"))

    def test_empty_not_free(self):
        self.assertFalse(branching.is_free_branch(""))


class TestGetProtectedBranches(unittest.TestCase):
    """Stage-aware protected set: {main, master} union SMM-declared
    protected_branches union ({integration_branch} when stage >= 3).

    Callers pass `stage` in rather than have the helper re-call
    get_branching_stage so the stage 1→2 auto-promote side effect
    fires once per hook chain, not twice.
    """

    def test_stage_zero_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=0)
            self.assertEqual(branching.get_protected_branches(smm, 0), set())

    def test_stage_one_includes_main_and_master(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertEqual(
                branching.get_protected_branches(smm, 1), {"main", "master"}
            )

    def test_stage_two_includes_main_and_master(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=2)
            self.assertEqual(
                branching.get_protected_branches(smm, 2), {"main", "master"}
            )

    def test_stage_two_unions_declared_protected_branches(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=2, protected_branches=["release"])
            self.assertEqual(
                branching.get_protected_branches(smm, 2),
                {"main", "master", "release"},
            )

    def test_stage_three_includes_integration_branch(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch="develop")
            self.assertEqual(
                branching.get_protected_branches(smm, 3),
                {"main", "master", "develop"},
            )

    def test_stage_three_unions_declared_and_integration(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(
                smm,
                stage=3,
                protected_branches=["main"],
                integration_branch="develop",
            )
            self.assertEqual(
                branching.get_protected_branches(smm, 3),
                {"main", "master", "develop"},
            )

    def test_stage_three_without_integration_falls_back_to_main(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3)
            self.assertEqual(
                branching.get_protected_branches(smm, 3), {"main", "master"}
            )


class TestIsProtectedBranch(unittest.TestCase):
    def test_main_protected_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertTrue(branching.is_protected_branch(1, "main", smm))

    def test_master_protected_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertTrue(branching.is_protected_branch(1, "master", smm))

    def test_main_protected_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=2)
            self.assertTrue(branching.is_protected_branch(2, "main", smm))

    def test_not_protected_at_stage_0(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=0)
            self.assertFalse(branching.is_protected_branch(0, "main", smm))

    def test_feature_branch_not_protected(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertFalse(
                branching.is_protected_branch(1, "paul/story-001-feat", smm)
            )

    def test_empty_branch_not_protected(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertFalse(branching.is_protected_branch(1, "", smm))

    def test_custom_integration_branch_protected_at_stage_3(self):
        """The user-reported symptom: at stage 3 with integration_branch=
        develop, direct commits to develop must trigger the protected-branch
        block (today they sneak through because the hardcoded set ignores SMM).
        """
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch="develop")
            self.assertTrue(branching.is_protected_branch(3, "develop", smm))

    def test_main_still_protected_at_stage_3(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch="develop")
            self.assertTrue(branching.is_protected_branch(3, "main", smm))

    def test_feature_branch_not_protected_at_stage_3(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch="develop")
            self.assertFalse(
                branching.is_protected_branch(3, "paul/free-2026-05-19-foo", smm)
            )

    def test_declared_protected_branch_blocked_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=2, protected_branches=["release"])
            self.assertTrue(branching.is_protected_branch(2, "release", smm))


class TestGetPrimaryBranch(unittest.TestCase):
    def test_returns_main_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_main_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=2)
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_integration_branch_at_stage_3(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch="develop")
            self.assertEqual(branching.get_primary_branch(smm), "develop")

    def test_falls_back_to_main_at_stage_3_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3)
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_falls_back_to_main_at_stage_3_when_null(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=3, integration_branch=None)
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_main_when_no_system_context(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(branching.get_primary_branch(Path(td)), "main")

    def test_at_stage_1_triggers_auto_promote(self):
        """Routing through get_branching_stage means primary-branch reads
        also fire the Stage 1 -> 2 auto-promote side-effect — single
        chokepoint for stage progression.
        """
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            write_system_context(smm, stage=1)
            self.assertEqual(
                json.loads((smm / "system_context.json").read_text())[
                    "branching_strategy"
                ]["stage"],
                1,
            )
            self.assertEqual(branching.get_primary_branch(smm), "main")
            self.assertEqual(
                json.loads((smm / "system_context.json").read_text())[
                    "branching_strategy"
                ]["stage"],
                2,
            )


class TestGetMergeTarget(unittest.TestCase):
    def _setup_smm(self, td: str, *, stage: int, plan_branch: str | None) -> Path:
        smm = Path(td)
        ctx = {"branching_strategy": {"stage": stage}}
        (smm / "system_context.json").write_text(json.dumps(ctx))
        plan = {
            "title": "T",
            "sources": [],
            "overview": "o",
            "milestones": [],
        }
        if plan_branch is not None:
            plan["branch"] = plan_branch
        execution_plan_store.save_plan(smm, plan, enforce_budget=False)
        return smm

    def test_returns_plan_branch_when_set_and_exists(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._setup_smm(td, stage=2, plan_branch="paul/plan-redesign")
            with patch("branching.branch_exists", return_value=True):
                result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "paul/plan-redesign")

    def test_falls_back_when_plan_branch_missing_locally(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._setup_smm(td, stage=2, plan_branch="paul/plan-redesign")
            with patch("branching.branch_exists", return_value=False):
                result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "main")

    def test_falls_back_when_plan_branch_unset(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._setup_smm(td, stage=2, plan_branch=None)
            result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "main")

    def test_falls_back_when_no_plan(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            (smm / "system_context.json").write_text(
                json.dumps({"branching_strategy": {"stage": 2}})
            )
            result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "main")

    def test_uses_get_primary_branch_for_fallback_at_stage_3(self):
        with tempfile.TemporaryDirectory() as td:
            smm = Path(td)
            ctx = {
                "branching_strategy": {
                    "stage": 3,
                    "integration_branch": "develop",
                }
            }
            (smm / "system_context.json").write_text(json.dumps(ctx))
            result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "develop")


class TestAutoPromote(_SMMTestCase):
    """Stage 1 -> Stage 2 auto-promotion (M-7 plugin floor)."""

    def _write_ctx(self, stage: int) -> None:
        doc = valid_doc(branching_strategy={"stage": stage})
        (self.smm_dir / "system_context.json").write_text(json.dumps(doc))

    def _stage_in_file(self) -> int:
        ctx = json.loads((self.smm_dir / "system_context.json").read_text())
        return ctx["branching_strategy"]["stage"]

    def _promote_events(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("topic") == "branching-stage-auto-promote"
        ]

    def test_promotes_stage_1_to_2_in_file(self):
        self._write_ctx(1)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(self._stage_in_file(), 2)

    def test_emits_one_decision_event(self):
        self._write_ctx(1)
        branching.get_branching_stage(self.smm_dir)
        events = self._promote_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], EVENT_TYPE_DECISION)
        self.assertEqual(events[0]["agent_id"], "branching")

    def test_idempotent_no_duplicate_event(self):
        self._write_ctx(1)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(len(self._promote_events()), 1)

    def test_stage_0_unchanged(self):
        self._write_ctx(0)
        before = (self.smm_dir / "system_context.json").read_text()
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 0)
        self.assertEqual((self.smm_dir / "system_context.json").read_text(), before)
        self.assertEqual(self._promote_events(), [])

    def test_stage_2_unchanged(self):
        self._write_ctx(2)
        before = (self.smm_dir / "system_context.json").read_text()
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual((self.smm_dir / "system_context.json").read_text(), before)
        self.assertEqual(self._promote_events(), [])

    def test_missing_system_context_returns_zero(self):
        self.assertFalse((self.smm_dir / "system_context.json").exists())
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 0)
        self.assertEqual(self._promote_events(), [])

    def test_create_sprint_branch_promotes_stage_1_e2e(self):
        """E2E AC for story-001: a Stage 1 fixture, when create_sprint_branch
        runs (which reads stage internally via get_branching_stage), the
        sprint branch IS created (the stage>=2 floor gate passes because
        auto-promote ran transparently) AND the persisted file now reads
        stage=2 for subsequent reads.

        Mocks the git subprocess + identity + push surfaces so the test
        exercises the composition (_create_or_resume_branch -> stage gate
        -> get_branching_stage -> auto-promote) without a real git repo.
        """
        self._write_ctx(1)

        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("branching.identity.user_namespace", return_value="paul"),
            patch("branching.branch_exists", return_value=False),
            patch("branching.is_worktree_clean", return_value=True),
            patch("branching._git", return_value=fake_proc),
        ):
            result = branching.create_sprint_branch(
                cwd=str(self.smm_dir),
                sprint_id="sprint-001",
                slug="e2e",
                smm_dir=self.smm_dir,
            )
        self.assertEqual(result, "paul/sprint-001-e2e")
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(len(self._promote_events()), 1)

    def test_create_story_branch_promotes_stage_1_e2e(self):
        """E2E AC for story-001: a Stage 1 fixture, when create_story_branch
        runs (which reads stage internally via get_branching_stage through
        _create_or_resume_branch), the story branch IS created (the
        stage>=2 floor gate passes because auto-promote ran transparently)
        AND the persisted file now reads stage=2.

        Mirrors test_create_sprint_branch_promotes_stage_1_e2e but for the
        story-branch path. Pins the contract that the auto-promote
        chokepoint fires on every stage-aware branch-create entry, not
        just the sprint path.
        """
        self._write_ctx(1)

        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("branching.identity.user_namespace", return_value="paul"),
            patch("branching.branch_exists", return_value=False),
            patch("branching.is_worktree_clean", return_value=True),
            patch("branching._git", return_value=fake_proc),
            # short-circuits the post-create set_story_branch lookup
            patch("branching.sprint_store.sprint_exists", return_value=False),
        ):
            result = branching.create_story_branch(
                cwd=str(self.smm_dir),
                story_id="story-001",
                slug="e2e",
                smm_dir=self.smm_dir,
                base="main",
            )
        self.assertEqual(result, "paul/story-001-e2e")
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(len(self._promote_events()), 1)


class TestIsGitWorktree(unittest.TestCase):
    """is_git_worktree distinguishes a checkable working tree from a path that
    can't be status-checked at all (missing dir / not a repo), so callers don't
    conflate an errored `git status` with a dirty tree."""

    def test_real_repo_is_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True, check=True)
            self.assertTrue(branching.is_git_worktree(td))

    def test_non_repo_dir_is_not_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(branching.is_git_worktree(td))

    def test_missing_path_is_not_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "does-not-exist")
            # A missing cwd makes subprocess raise, not return non-zero — the
            # helper must swallow that and report "not a worktree", never crash.
            self.assertFalse(branching.is_git_worktree(missing))

    def test_hung_git_timeout_is_not_worktree(self):
        # _git runs with a timeout, so a hung `git rev-parse` raises
        # TimeoutExpired (a SubprocessError, not OSError). The helper must
        # swallow it and report "not a worktree" rather than crash the merge.
        with patch.object(
            branching,
            "_git",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            self.assertFalse(branching.is_git_worktree("/any/path"))


if __name__ == "__main__":
    unittest.main()
