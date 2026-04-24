#!/usr/bin/env python3
"""Tests for plan_cli.py: CLI wrapper for execution plan operations.

Subprocess tests verify exit codes and stdout for key commands.
Store logic is tested in test_execution_plan_store.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import VALID_MILESTONE as _VALID_MILESTONE
from conftest import _SMMTestCase, run_cli
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


class TestAddMilestoneCommand(_SMMTestCase):
    def test_add_milestone(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_m = _VALID_MILESTONE.copy()
        new_m["number"] = 2
        new_m["name"] = "Second Milestone"
        result = run_cli(_CLI, ["add-milestone"], self.smm_dir, json.dumps(new_m))
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(len(loaded["milestones"]), 2)
        self.assertEqual(loaded["milestones"][1]["name"], "Second Milestone")

    def test_add_milestone_no_plan(self):
        result = run_cli(
            _CLI,
            ["add-milestone"],
            self.smm_dir,
            json.dumps(_VALID_MILESTONE),
        )
        self.assertNotEqual(result.returncode, 0)


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


class TestUpdateStatusCommand(_SMMTestCase):
    def test_update_to_in_progress(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["update-status", "1", "in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "in-progress")

    def test_update_to_delivered(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(
            _CLI,
            [
                "update-status",
                "1",
                "delivered",
                "--delivered-sprint",
                "sprint-005",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "delivered")
        self.assertEqual(loaded["milestones"][0]["delivered_sprint"], "sprint-005")

    def test_delivered_without_sprint_fails(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["update-status", "1", "delivered"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_milestone_number(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["update-status", "99", "in-progress"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_update_to_deferred(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = run_cli(_CLI, ["update-status", "1", "deferred"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "deferred")


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


class TestEditMilestoneCommand(_SMMTestCase):
    def test_edit_milestone_name(self):
        """Edit a simple string field on a milestone."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "Updated Name"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["name"], "Updated Name")

    def test_edit_milestone_change_zones(self):
        """Edit a complex field (list of objects)."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_zones = [{"path": "new.py", "note": "added"}]
        patch = json.dumps({"change_zones": new_zones})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["change_zones"], new_zones)

    def test_edit_milestone_multiple_fields(self):
        """Patch multiple fields at once."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"goal": "New goal", "done": "New done"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["goal"], "New goal")
        self.assertEqual(loaded["milestones"][0]["done"], "New done")

    def test_edit_milestone_invalid_number(self):
        """Non-existent milestone number fails."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "X"})
        result = run_cli(_CLI, ["edit-milestone", "99"], self.smm_dir, stdin_data=patch)
        self.assertNotEqual(result.returncode, 0)

    def test_edit_milestone_preserves_other_fields(self):
        """Fields not in the patch are preserved."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "New Name"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        # Original goal preserved
        self.assertEqual(loaded["milestones"][0]["goal"], "Build the foundation")


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


class TestMilestoneAcceptanceExecution(_SMMTestCase):
    """Milestone-level acceptance_execution validation and rendering."""

    def _valid_ae(self):
        return {"type": "pytest", "command": "pytest tests/acceptance/"}

    def _plan_with_ae(self, ae):
        m = _VALID_MILESTONE.copy()
        m["acceptance_execution"] = ae
        return _make_plan(milestones=[m])

    def test_valid_acceptance_execution_passes(self):
        plan = self._plan_with_ae(self._valid_ae())
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_acceptance_execution_passes(self):
        plan = _make_plan()
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_acceptance_execution_missing_type_fails(self):
        plan = self._plan_with_ae({"command": "pytest"})
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("type", result.stderr)

    def test_acceptance_execution_missing_command_fails(self):
        plan = self._plan_with_ae({"type": "pytest"})
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("command", result.stderr)

    def test_acceptance_execution_with_optional_fields(self):
        ae = {
            "type": "playwright",
            "command": "npx playwright test",
            "setup": "docker compose up -d",
            "notes": "Requires backend on :3000",
        }
        plan = self._plan_with_ae(ae)
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_render_includes_acceptance_execution(self):
        plan = self._plan_with_ae(self._valid_ae())
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Acceptance Execution", result.stdout)
        self.assertIn("pytest", result.stdout)

    def test_render_omits_acceptance_execution_when_absent(self):
        plan = _make_plan()
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Acceptance Execution", result.stdout)

    def test_acceptance_execution_non_string_setup_fails(self):
        ae = {"type": "pytest", "command": "pytest", "setup": 42}
        plan = self._plan_with_ae(ae)
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup", result.stderr)

    def test_acceptance_execution_non_string_notes_fails(self):
        ae = {"type": "pytest", "command": "pytest", "notes": True}
        plan = self._plan_with_ae(ae)
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(plan))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes", result.stderr)

    def test_edit_milestone_adds_acceptance_execution(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"acceptance_execution": self._valid_ae()})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        ae = loaded["milestones"][0]["acceptance_execution"]
        self.assertEqual(ae["type"], "pytest")
        self.assertEqual(ae["command"], "pytest tests/acceptance/")


class TestPlanCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


if __name__ == "__main__":
    unittest.main()
