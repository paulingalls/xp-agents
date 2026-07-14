#!/usr/bin/env python3
"""Tests for plan_cli.py's PLAN-level and query subcommands.

Subprocess tests verify exit codes and stdout for key commands.
Store logic is tested in test_execution_plan_store.py.

The milestone-scoped subcommands (add-milestone, update-status, edit-milestone,
and milestone acceptance_execution) live in test_plan_cli_milestones.py — split
off when this file crossed the 500-line cap. The seam is the unit a command
operates on: whole plan here, one milestone there.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import VALID_MILESTONE as _VALID_MILESTONE
from conftest import _SMMTestCase, run_cli
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan

_CLI = Path(__file__).parent.parent.parent / "smm" / "plan_cli.py"


class TestExistsCommand(_SMMTestCase):
    def test_exists_when_plan_present(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists_when_missing(self):
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestHasRemainingCommand(_SMMTestCase):
    def test_remaining_when_planned(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_no_remaining_when_all_delivered(self):
        m = _VALID_MILESTONE.copy()
        m["status"] = "delivered"
        m["delivered_sprint"] = "sprint-001"
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=[m]))
        )
        result = run_cli(_CLI, ["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_no_remaining_when_no_plan(self):
        result = run_cli(_CLI, ["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestCountCommand(_SMMTestCase):
    def test_count_output(self):
        m2 = _VALID_MILESTONE.copy()
        m2["number"] = 2
        m2["status"] = "delivered"
        m2["delivered_sprint"] = "sprint-001"
        m3 = _VALID_MILESTONE.copy()
        m3["number"] = 3
        m3["status"] = "deferred"
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=[_VALID_MILESTONE.copy(), m2, m3]))
        )
        result = run_cli(_CLI, ["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("planned=1", result.stdout)
        self.assertIn("delivered=1", result.stdout)
        self.assertIn("deferred=1", result.stdout)

    def test_count_missing_plan(self):
        result = run_cli(_CLI, ["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("planned=0", result.stdout)
        self.assertIn("deferred=0", result.stdout)


class TestCreateCommand(_SMMTestCase):
    def test_create_plan(self):
        plan = _make_plan(title="New Plan")
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "execution_plan.json").exists())
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["title"], "New Plan")

    def test_create_invalid_plan(self):
        result = run_cli(_CLI, ["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)

    def test_create_clears_marker(self):
        marker = self.smm_dir / ".needs-execution-plan"
        marker.write_text("startup")
        plan = _make_plan()
        run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertFalse(marker.exists())


class TestAddSourceCommand(_SMMTestCase):
    def test_add_source(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_src = {
            "label": "New Source",
            "location": "docs/new.md",
            "type": "repo",
            "content": None,
        }
        result = run_cli(_CLI, ["add-source"], self.smm_dir, json.dumps(new_src))
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(len(loaded["sources"]), 2)


class TestSetOverviewCommand(_SMMTestCase):
    def test_set_overview(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["set-overview"], self.smm_dir, "New overview text.")
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["overview"], "New overview text.")


class TestRenderCommand(_SMMTestCase):
    def test_render_output(self):
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(title="My Plan"))
        )
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("# Execution Plan: My Plan", result.stdout)
        self.assertIn("Foundation", result.stdout)

    def test_render_missing_plan(self):
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestArchiveCommand(_SMMTestCase):
    def test_archive_moves_file(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["archive"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.smm_dir / "execution_plan.json").exists())
        self.assertTrue((self.smm_dir / "plans").is_dir())

    def test_archive_missing_plan(self):
        result = run_cli(_CLI, ["archive"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestSetBranchCommand(_SMMTestCase):
    def test_set_branch_writes_field(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["set-branch", "paulingalls/plan-foo"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["branch"], "paulingalls/plan-foo")

    def test_set_branch_empty_clears_field(self):
        plan = _make_plan(branch="user/old-branch")
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["set-branch", ""], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertIsNone(loaded["branch"])

    def test_set_branch_overwrites_existing(self):
        plan = _make_plan(branch="user/old")
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["set-branch", "user/new"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["branch"], "user/new")

    def test_set_branch_no_plan_fails(self):
        result = run_cli(_CLI, ["set-branch", "user/foo"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_set_branch_invalid_name_fails(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["set-branch", "has space"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_set_branch_grandfathers_surface_drift(self):
        # set-branch is a mutate path: post-authoring acceptance_surface drift
        # against an untouched surfaces_touched FK must not block the resave.
        from _system_context_fixtures import surfaces as _surfaces
        from _system_context_fixtures import valid_doc
        from system_context_schema import SYSTEM_CONTEXT_FILENAME

        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=_surfaces("cli", "sdk")))
        )
        plan = _make_plan(milestones=[_make_milestone(surfaces_touched=["sdk"])])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        # Drop 'sdk' from acceptance_surfaces, then flip the branch.
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=_surfaces("cli")))
        )
        result = run_cli(_CLI, ["set-branch", "user/new"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["branch"], "user/new")


class TestGetBranchCommand(_SMMTestCase):
    def test_get_branch_prints_value(self):
        plan = _make_plan(branch="paulingalls/plan-foo")
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["get-branch"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "paulingalls/plan-foo")

    def test_get_branch_empty_when_null(self):
        plan = _make_plan(branch=None)
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["get-branch"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_get_branch_empty_when_absent(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["get-branch"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_get_branch_no_plan_fails(self):
        result = run_cli(_CLI, ["get-branch"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestIsPlanCompleteCommand(_SMMTestCase):
    def _write(self, milestones: list[dict]) -> None:
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=milestones))
        )

    def test_all_delivered_exits_zero(self):
        m = _VALID_MILESTONE.copy()
        m["status"] = "delivered"
        m["delivered_sprint"] = "sprint-001"
        self._write([m])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_all_deferred_exits_zero(self):
        m = _VALID_MILESTONE.copy()
        m["status"] = "deferred"
        self._write([m])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_mix_delivered_and_deferred_exits_zero(self):
        m1 = _VALID_MILESTONE.copy()
        m1["status"] = "delivered"
        m1["delivered_sprint"] = "sprint-001"
        m2 = _VALID_MILESTONE.copy()
        m2["number"] = 2
        m2["status"] = "deferred"
        self._write([m1, m2])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_any_planned_exits_one(self):
        m1 = _VALID_MILESTONE.copy()
        m1["status"] = "delivered"
        m1["delivered_sprint"] = "sprint-001"
        m2 = _VALID_MILESTONE.copy()
        m2["number"] = 2
        m2["status"] = "planned"
        self._write([m1, m2])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_any_in_progress_exits_one(self):
        m = _VALID_MILESTONE.copy()
        m["status"] = "in-progress"
        self._write([m])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_no_plan_fails(self):
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No execution plan", result.stderr)

    def test_empty_milestones_exits_zero(self):
        """A plan with no milestones is trivially complete (no remaining work)."""
        self._write([])
        result = run_cli(_CLI, ["is-plan-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)


class TestPlanCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()
