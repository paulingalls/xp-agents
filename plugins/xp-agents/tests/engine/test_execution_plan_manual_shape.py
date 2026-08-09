#!/usr/bin/env python3
"""Tests for the milestone-level manual-acceptance-shape rule.

Ports the story-level mechanism (_manual_shape_exemption.grandfathered_story_ids,
exercised in test_sprint_store.py's TestManualShapeAtAuthoring /
TestManualShapeGrandfathering) to milestones. New file rather than additions to
test_execution_plan_schema.py or test_execution_plan_store.py — both already sit
against the 500-line test-file-size floor (see test_file_size_pin.py).

Cycle A (this file's first classes): the shared exemption helper,
`grandfathered_milestone_numbers`, tested directly against disk state — the
rule is not wired into validate_plan/save_plan yet.

Cycle B: authoring-refusal and read-path tests once the rule is wired live —
save_plan refuses an authored manual+command milestone, resaves a stored one
unchanged, and plan_cli's add-milestone/edit-milestone refuse it end-to-end.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan

_PLAN_CLI = Path(__file__).parent.parent.parent / "smm" / "plan_cli.py"

_PROSE_MANUAL = {"type": "manual", "command": "go read the logs and confirm X"}


class TestGrandfatheredMilestoneNumbersExemption(_SMMTestCase):
    """`grandfathered_milestone_numbers` derives the exemption set from disk.

    Mirrors TestManualShapeGrandfathering's scenarios but calls the helper
    directly — the rule is not yet wired into validate_plan/save_plan.
    """

    def _store(self, plan: dict) -> None:
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))

    def test_exempt_when_stored_block_unchanged(self):
        import _manual_shape_exemption as exemption

        stored = _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
        self._store(_make_plan(milestones=[stored]))

        incoming = _make_plan(milestones=[dict(stored)])
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset({1}))

    def test_not_exempt_when_block_edited(self):
        import _manual_shape_exemption as exemption

        stored = _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
        self._store(_make_plan(milestones=[stored]))

        edited = dict(stored)
        edited["acceptance_execution"] = {
            "type": "manual",
            "command": "a different prose command",
        }
        incoming = _make_plan(milestones=[edited])
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_not_exempt_when_stored_block_is_not_manual_with_command(self):
        import _manual_shape_exemption as exemption

        stored = _make_milestone(
            number=1, acceptance_execution={"type": "pytest", "command": "pytest"}
        )
        self._store(_make_plan(milestones=[stored]))

        incoming = _make_plan(milestones=[dict(stored)])
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_empty_set_on_missing_plan(self):
        import _manual_shape_exemption as exemption

        incoming = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_empty_set_on_symlinked_plan(self):
        import _manual_shape_exemption as exemption

        real = self.smm_dir / "real_plan.json"
        stored = _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
        real.write_text(json.dumps(_make_plan(milestones=[stored])))
        (self.smm_dir / "execution_plan.json").symlink_to(real)

        incoming = _make_plan(milestones=[dict(stored)])
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_empty_set_on_corrupt_plan(self):
        import _manual_shape_exemption as exemption

        (self.smm_dir / "execution_plan.json").write_text("{not json at all")

        incoming = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_empty_set_when_stored_milestones_not_a_list(self):
        import _manual_shape_exemption as exemption

        self._store({"title": "X", "sources": [], "overview": "", "milestones": {}})

        incoming = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())

    def test_empty_set_when_incoming_milestones_not_a_list(self):
        import _manual_shape_exemption as exemption

        stored = _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
        self._store(_make_plan(milestones=[stored]))

        incoming = {"title": "X", "sources": [], "overview": "", "milestones": "nope"}
        result = exemption.grandfathered_milestone_numbers(self.smm_dir, incoming)
        self.assertEqual(result, frozenset())


class TestManualShapeAtMilestoneAuthoring(_SMMTestCase):
    """A milestone's manual acceptance block may not carry a command at
    authoring time — the same refusal the story level already enforces.
    """

    def test_save_rejects_prose_in_manual_command(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        with self.assertRaises(ValueError) as ctx:
            store.save_plan(self.smm_dir, plan)
        msg = str(ctx.exception)
        self.assertIn("command", msg)
        self.assertIn("manual", msg)
        self.assertIn("steps", msg)
        self.assertIn("milestones[0]", msg)

    def test_save_accepts_manual_with_steps_only(self):
        import execution_plan_store as store

        ae = {"type": "manual", "steps": ["Deploy to staging", "Confirm redirect"]}
        m = _make_milestone(number=1, acceptance_execution=ae)
        plan = _make_plan(milestones=[m])
        store.save_plan(self.smm_dir, plan)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["acceptance_execution"], ae)

    def test_save_accepts_non_manual_with_command(self):
        import execution_plan_store as store

        ae = {"type": "pytest", "command": "pytest tests/"}
        m = _make_milestone(number=1, acceptance_execution=ae)
        plan = _make_plan(milestones=[m])
        store.save_plan(self.smm_dir, plan)

    def test_missing_plan_grants_no_exemption(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        with self.assertRaises(ValueError):
            store.save_plan(self.smm_dir, plan)

    def test_corrupt_plan_grants_no_exemption(self):
        import execution_plan_store as store

        (self.smm_dir / "execution_plan.json").write_text("{bad json")
        plan = _make_plan(
            milestones=[
                _make_milestone(number=1, acceptance_execution=dict(_PROSE_MANUAL))
            ]
        )
        with self.assertRaises(ValueError):
            store.save_plan(self.smm_dir, plan)


class TestManualShapeMilestoneGrandfathering(_SMMTestCase):
    """A manual+command block ALREADY on disk keeps the plan editable.

    validate_plan walks every milestone on the read path too, so a
    flag-only rule would make an existing plan unloadable. The exemption is
    per milestone and covers only an UNCHANGED stored block.
    """

    def setUp(self):
        super().setUp()
        self.stored = _make_milestone(
            number=1, acceptance_execution=dict(_PROSE_MANUAL)
        )
        self.other = _make_milestone(number=2, name="Second Milestone")
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=[self.stored, self.other]))
        )

    def test_stored_block_still_loads(self):
        import execution_plan_store as store

        loaded = store.load_plan_required(self.smm_dir)
        self.assertEqual(loaded["milestones"][0]["acceptance_execution"], _PROSE_MANUAL)

    def test_unrelated_status_update_still_succeeds(self):
        import execution_plan_store as store

        store.update_milestone_status(self.smm_dir, 2, "in-progress")
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][1]["status"], "in-progress")
        self.assertEqual(loaded["milestones"][0]["acceptance_execution"], _PROSE_MANUAL)

    def test_editing_a_different_milestone_still_succeeds(self):
        import execution_plan_store as store

        plan = store.load_plan_required(self.smm_dir)
        store.find_milestone_required(plan, 2)["goal"] = "Rewritten goal"
        store.save_plan(self.smm_dir, plan)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][1]["goal"], "Rewritten goal")

    def test_editing_the_offending_block_is_rejected(self):
        import execution_plan_store as store

        plan = store.load_plan_required(self.smm_dir)
        store.find_milestone_required(plan, 1)["acceptance_execution"] = {
            "type": "manual",
            "command": "still prose",
        }
        with self.assertRaises(ValueError) as ctx:
            store.save_plan(self.smm_dir, plan)
        self.assertIn("steps", str(ctx.exception))


class TestPlanCliRefusesManualCommandEndToEnd(_SMMTestCase):
    """E2E: plan_cli, driven as a subprocess, refuses manual+command."""

    def test_add_milestone_refuses_and_leaves_plan_unchanged(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_m = _make_milestone(number=2, acceptance_execution=dict(_PROSE_MANUAL))
        before = (self.smm_dir / "execution_plan.json").read_text()

        result = run_cli(_PLAN_CLI, ["add-milestone"], self.smm_dir, json.dumps(new_m))
        self.assertNotEqual(result.returncode, 0)
        after = (self.smm_dir / "execution_plan.json").read_text()
        self.assertEqual(before, after)

    def test_edit_milestone_refuses_and_leaves_plan_unchanged(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        before = (self.smm_dir / "execution_plan.json").read_text()

        patch = json.dumps({"acceptance_execution": dict(_PROSE_MANUAL)})
        result = run_cli(
            _PLAN_CLI, ["edit-milestone", "1"], self.smm_dir, stdin_data=patch
        )
        self.assertNotEqual(result.returncode, 0)
        after = (self.smm_dir / "execution_plan.json").read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
