#!/usr/bin/env python3
"""Tests for branching.py — protected-branch / primary-branch / merge-target
resolution.

Covers: get_protected_branches, is_protected_branch, get_primary_branch,
get_merge_target.

Split from test_branching.py — pure branch-name/stage helpers remain there.
Commit message parsing tests (extract_commit_message,
is_escape_hatch_commit) are in test_commits.py.

Git-operation lifecycle tests (create, merge, delete, CLI) are in
test_branching_lifecycle.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching
import execution_plan_store
from _branching_fixtures import write_system_context


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
    """Patches branch_resolution.branch_exists, NOT branching.branch_exists.

    get_merge_target lives in branch_resolution and calls its OWN module's
    branch_exists (via _recorded_plan_branch), so a patch on branching's
    re-exported alias never reaches it — the tempdirs here are not git repos,
    so the real branch_exists would answer False and the plan branch would
    resolve to primary.
    """

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
            with patch("branch_resolution.branch_exists", return_value=True):
                result = branching.get_merge_target(smm, cwd=td)
            self.assertEqual(result, "paul/plan-redesign")

    def test_falls_back_when_plan_branch_missing_locally(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._setup_smm(td, stage=2, plan_branch="paul/plan-redesign")
            with patch("branch_resolution.branch_exists", return_value=False):
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


if __name__ == "__main__":
    unittest.main()
