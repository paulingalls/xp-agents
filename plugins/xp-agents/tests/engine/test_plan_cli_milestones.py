#!/usr/bin/env python3
"""Tests for plan_cli.py's MILESTONE-scoped subcommands.

Split from test_plan_cli.py (which keeps the plan-level and query commands:
create, archive, render, set-branch, is-plan-complete, ...) when it crossed the
500-line cap. The seam is the unit the command operates on, not chronology: every
subcommand here takes a milestone number and mutates one milestone.

That seam is also where the delivery invariant lives, which is why these belong
together. `update-status` is the ONE writer of `status`/`delivered_sprint` and
enforces their pairing; `edit-milestone` patches every other field and refuses
those two. Testing the two commands side by side is what keeps that split
honest — a patch path that could also write status would silently become a
second writer, bypassing the state machine.
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

    def test_edit_milestone_refuses_delivered(self):
        """A delivered milestone is a shipped record — patching it is refused.

        The rule lived only in skill prose, and prose does not stop a patch. The
        sprint reviewer records delivery through update-status (the sole writer
        of delivered_sprint); an edit-milestone patch would rewrite the record
        behind it, leaving the plan claiming a delivery that never happened.
        """
        plan = _make_plan()
        plan["milestones"][0]["status"] = "delivered"
        plan["milestones"][0]["delivered_sprint"] = "sprint-001"
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))

        patch = json.dumps({"goal": "Rewritten after the fact"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)

        self.assertNotEqual(result.returncode, 0)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["goal"], "Build the foundation")
        self.assertEqual(loaded["milestones"][0]["delivered_sprint"], "sprint-001")

    def test_edit_milestone_refuses_to_declare_a_delivery(self):
        """Refusing to patch a DELIVERED milestone is only half the guard.

        Nothing stopped a patch from *declaring* one. `{"status": "delivered",
        "delivered_sprint": ...}` on a planned milestone satisfies the schema
        (which only requires the two appear together), so the plan records a ship
        that never happened — and the guard above then makes it permanent: the
        forged milestone can no longer be edited back.

        `update_milestone_status` owns this transition and enforces its rules
        (delivered_sprint required for delivered, cleared on any move away from
        it). A patch that writes `status` bypasses that state machine entirely,
        so the patch path must not write it at all — which is what the guard's
        own comment, "update-status is the only writer of delivered_sprint",
        already claims.

        Downstream this is not cosmetic: the retro reads milestone status to
        decide which milestones still schedule work, so a forged status silently
        changes what it tells the user about an aging debt.
        """
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))

        patch = json.dumps({"status": "delivered", "delivered_sprint": "sprint-999"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("update-status", result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "planned")
        self.assertIsNone(loaded["milestones"][0]["delivered_sprint"])

    def test_edit_milestone_refuses_any_status_patch(self):
        """Not just `delivered` — `status` is update-status's field, full stop.

        A patched `deferred` is the same bypass wearing a different hat, and it
        lands on the same consumer: a deferred milestone schedules nothing, so
        the retro stops reporting its debts as scheduled.
        """
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))

        patch = json.dumps({"status": "deferred"})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)

        self.assertNotEqual(result.returncode, 0)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "planned")

    def test_edit_milestone_still_patches_ordinary_fields(self):
        """The refusal is scoped to the delivery fields — `schedules`, the field
        this path exists to let a late-recorded debt reach, still lands."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))

        patch = json.dumps({"schedules": ["4ecd48c71327"]})
        result = run_cli(_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch)

        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["schedules"], ["4ecd48c71327"])


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


if __name__ == "__main__":
    unittest.main()
