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
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase


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


class TestIsProtectedBranch(unittest.TestCase):
    def test_main_protected_at_stage_1(self):
        self.assertTrue(branching.is_protected_branch(1, "main"))

    def test_master_protected_at_stage_1(self):
        self.assertTrue(branching.is_protected_branch(1, "master"))

    def test_main_protected_at_stage_2(self):
        self.assertTrue(branching.is_protected_branch(2, "main"))

    def test_not_protected_at_stage_0(self):
        self.assertFalse(branching.is_protected_branch(0, "main"))

    def test_feature_branch_not_protected(self):
        self.assertFalse(branching.is_protected_branch(1, "paul/story-001-feat"))

    def test_empty_branch_not_protected(self):
        self.assertFalse(branching.is_protected_branch(1, ""))


class TestGetPrimaryBranch(unittest.TestCase):
    def _write_ctx(self, td: str, ctx: dict) -> Path:
        p = Path(td)
        (p / "system_context.json").write_text(json.dumps(ctx))
        return p

    def test_returns_main_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._write_ctx(td, {"branching_strategy": {"stage": 1}})
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_main_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._write_ctx(td, {"branching_strategy": {"stage": 2}})
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_integration_branch_at_stage_3(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "branching_strategy": {
                    "stage": 3,
                    "integration_branch": "develop",
                }
            }
            smm = self._write_ctx(td, ctx)
            self.assertEqual(branching.get_primary_branch(smm), "develop")

    def test_falls_back_to_main_at_stage_3_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            smm = self._write_ctx(td, {"branching_strategy": {"stage": 3}})
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_falls_back_to_main_at_stage_3_when_null(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "branching_strategy": {
                    "stage": 3,
                    "integration_branch": None,
                }
            }
            smm = self._write_ctx(td, ctx)
            self.assertEqual(branching.get_primary_branch(smm), "main")

    def test_returns_main_when_no_system_context(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(branching.get_primary_branch(Path(td)), "main")


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
        self.assertEqual(events[0]["type"], "decision")
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


if __name__ == "__main__":
    unittest.main()
