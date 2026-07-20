#!/usr/bin/env python3
"""Tests for branching.py — pure-function unit tests.

Covers: branch_name, sprint_branch_name, get_branching_stage,
is_sprint_branch, is_free_branch.

Commit message parsing tests (extract_commit_message,
is_escape_hatch_commit) are in test_commits.py.

Protected/primary/merge-target branch resolution is in
test_branching_protection.py. Stage auto-promotion and worktree detection
are in test_branching_stage_gate.py. Git-operation lifecycle tests (create,
merge, delete, CLI) are in test_branching_lifecycle.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching


class TestBranchLifecycleShimImports(unittest.TestCase):
    """Catch cascade failure in <1s when branch_lifecycle extraction
    breaks the backwards-compat re-exports — per wisdom ab40b12643ab,
    a one-line shim-import test fails fast instead of waiting for
    80 downstream tests to red.
    """

    def test_lifecycle_symbols_resolve_via_branching(self):
        from branching import (
            _fast_forward_if_safe,
            _merge_into_target,
            delete_branch,
            is_merged_into,
            merge_branch,
            survives_delete_of,
        )

        for fn in (
            delete_branch,
            merge_branch,
            is_merged_into,
            survives_delete_of,
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


if __name__ == "__main__":
    unittest.main()
