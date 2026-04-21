#!/usr/bin/env python3
"""Tests for per-field maxLength enforcement in execution_plan_schema.py.

Extracted from test_execution_plan_store.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan


class TestMilestoneFieldBudgets(unittest.TestCase):
    """Test per-field maxLength enforcement in validate_plan()."""

    def test_goal_over_budget_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(goal="x" * 201)])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("goal" in e and "201" in e and "200" in e for e in errors))

    def test_goal_at_budget_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(goal="x" * 200)])
        errors = schema.validate_plan(plan)
        self.assertFalse(any("goal" in e and "budget" in e for e in errors))

    def test_done_over_budget_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(done="x" * 301)])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("done" in e and "301" in e and "300" in e for e in errors))

    def test_done_at_budget_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(done="x" * 300)])
        errors = schema.validate_plan(plan)
        self.assertFalse(any("done" in e and "budget" in e for e in errors))

    def test_design_details_over_budget_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(design_details="x" * 501)])
        errors = schema.validate_plan(plan)
        self.assertTrue(
            any("design_details" in e and "501" in e and "500" in e for e in errors)
        )

    def test_design_details_at_budget_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(design_details="x" * 500)])
        errors = schema.validate_plan(plan)
        self.assertFalse(any("design_details" in e and "budget" in e for e in errors))

    def test_constraint_item_over_budget_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(constraints=["x" * 151])])
        errors = schema.validate_plan(plan)
        self.assertTrue(
            any("constraints" in e and "151" in e and "150" in e for e in errors)
        )

    def test_constraint_item_at_budget_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(constraints=["x" * 150])])
        errors = schema.validate_plan(plan)
        self.assertFalse(any("constraints" in e and "budget" in e for e in errors))

    def test_change_zone_note_over_budget_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    change_zones=[{"path": "src/foo.py", "note": "x" * 151}]
                )
            ]
        )
        errors = schema.validate_plan(plan)
        self.assertTrue(any("note" in e and "151" in e and "150" in e for e in errors))

    def test_change_zone_note_at_budget_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    change_zones=[{"path": "src/foo.py", "note": "x" * 150}]
                )
            ]
        )
        errors = schema.validate_plan(plan)
        self.assertFalse(any("note" in e and "budget" in e for e in errors))

    def test_change_zone_without_note_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(change_zones=[{"path": "src/foo.py"}])]
        )
        errors = schema.validate_plan(plan)
        self.assertEqual(errors, [])

    def test_design_details_non_string_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(design_details=123)])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("design_details" in e for e in errors))

    def test_constraint_non_string_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(constraints=[123])])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("must be a string" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
