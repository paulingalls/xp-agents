#!/usr/bin/env python3
"""Tests for execution_plan_schema.py — pure validation logic."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import VALID_SOURCE as _VALID_SOURCE
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan


class TestValidatePlan(unittest.TestCase):
    """Test execution_plan_schema.validate_plan()."""

    def test_valid_plan_no_errors(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan(_make_plan())
        self.assertEqual(errors, [])

    def test_not_a_dict(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan("not a dict")
        self.assertEqual(len(errors), 1)
        self.assertIn("must be an object", errors[0])

    def test_missing_required_fields(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan({})
        self.assertGreaterEqual(len(errors), 4)
        for field in ("title", "sources", "overview", "milestones"):
            self.assertTrue(
                any(field in e for e in errors), f"Missing error for {field}"
            )

    def test_title_must_be_string(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan(_make_plan(title=123))
        self.assertTrue(any("title" in e for e in errors))

    def test_overview_must_be_string(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan(_make_plan(overview=123))
        self.assertTrue(any("overview" in e for e in errors))

    def test_sources_must_be_list(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan(_make_plan(sources="not a list"))
        self.assertTrue(any("sources" in e for e in errors))

    def test_milestones_must_be_list(self):
        import execution_plan_schema as schema

        errors = schema.validate_plan(_make_plan(milestones="not a list"))
        self.assertTrue(any("milestones" in e for e in errors))

    def test_invalid_milestone_status(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(status="bogus")])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("status" in e for e in errors))

    def test_valid_statuses_accepted(self):
        import execution_plan_schema as schema

        for status in ("planned", "in-progress"):
            plan = _make_plan(milestones=[_make_milestone(status=status)])
            errors = schema.validate_plan(plan)
            self.assertEqual(errors, [], f"Status {status!r} should be valid")
        plan = _make_plan(
            milestones=[
                _make_milestone(status="delivered", delivered_sprint="sprint-001")
            ]
        )
        errors = schema.validate_plan(plan)
        self.assertEqual(errors, [], "Status 'delivered' should be valid")

    def test_milestone_missing_required_fields(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[{"number": 1}])
        errors = schema.validate_plan(plan)
        self.assertGreater(len(errors), 0)

    def test_milestone_number_must_be_int(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(number="one")])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("number" in e for e in errors))

    def test_change_zones_must_be_list(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(change_zones="not list")])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("change_zones" in e for e in errors))

    def test_change_zone_entry_must_have_path(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(change_zones=[{"note": "missing path"}])]
        )
        errors = schema.validate_plan(plan)
        self.assertTrue(any("path" in e for e in errors))

    def test_source_missing_required_fields(self):
        import execution_plan_schema as schema

        plan = _make_plan(sources=[{"label": "only label"}])
        errors = schema.validate_plan(plan)
        self.assertGreater(len(errors), 0)

    def test_source_invalid_type(self):
        import execution_plan_schema as schema

        plan = _make_plan(sources=[{**_VALID_SOURCE, "type": "invalid"}])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("type" in e for e in errors))

    def test_delivered_milestone_requires_delivered_sprint(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(status="delivered", delivered_sprint=None)]
        )
        errors = schema.validate_plan(plan)
        self.assertTrue(any("delivered_sprint" in e for e in errors))

    def test_delivered_milestone_with_sprint_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[
                _make_milestone(status="delivered", delivered_sprint="sprint-001")
            ]
        )
        errors = schema.validate_plan(plan)
        self.assertEqual(errors, [])


class TestDeferredMilestoneStatus(unittest.TestCase):
    """`deferred` is a valid milestone status; no delivered_sprint required."""

    def test_deferred_status_accepted(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(status="deferred", delivered_sprint=None)]
        )
        self.assertEqual(schema.validate_plan(plan), [])

    def test_deferred_does_not_require_delivered_sprint(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(status="deferred", delivered_sprint=None)]
        )
        errors = schema.validate_plan(plan)
        self.assertFalse(any("delivered_sprint" in e for e in errors))

    def test_deferred_in_valid_statuses_constant(self):
        import execution_plan_schema as schema

        self.assertIn("deferred", schema.VALID_MILESTONE_STATUSES)

    def test_planned_with_no_delivered_sprint_still_valid(self):
        """Regression: relaxing delivered_sprint check must not break planned."""
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(status="planned", delivered_sprint=None)]
        )
        self.assertEqual(schema.validate_plan(plan), [])

    def test_delivered_still_requires_delivered_sprint(self):
        """Regression: relaxing the check must not weaken the delivered case."""
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(status="delivered", delivered_sprint=None)]
        )
        errors = schema.validate_plan(plan)
        self.assertTrue(any("delivered_sprint" in e for e in errors))


class TestPlanBranchField(unittest.TestCase):
    """Test that the optional `branch` field on the plan is validated."""

    def test_branch_absent_is_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan()
        self.assertNotIn("branch", plan)
        self.assertEqual(schema.validate_plan(plan), [])

    def test_branch_null_is_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan(branch=None)
        self.assertEqual(schema.validate_plan(plan), [])

    def test_branch_valid_names_accepted(self):
        import execution_plan_schema as schema

        for name in (
            "paulingalls/plan-foo",
            "user/plan-branch-lifecycle",
            "feature_x",
            "v1.2.3",
            "a/b/c",
        ):
            plan = _make_plan(branch=name)
            self.assertEqual(
                schema.validate_plan(plan), [], f"{name!r} should be valid"
            )

    def test_branch_invalid_names_rejected(self):
        import execution_plan_schema as schema

        for name in (
            "has space",
            "tab\there",
            "ctrl\x01char",
            "trailing/",
            "/leading",
            "double//slash",
            "special?char",
            "tilde~here",
            "caret^here",
            "colon:here",
            "asterisk*here",
            "open[bracket",
            "back\\slash",
        ):
            plan = _make_plan(branch=name)
            errors = schema.validate_plan(plan)
            self.assertTrue(
                any("branch" in e for e in errors),
                f"{name!r} should be rejected, got errors: {errors}",
            )

    def test_branch_must_be_string(self):
        import execution_plan_schema as schema

        plan = _make_plan(branch=123)
        errors = schema.validate_plan(plan)
        self.assertTrue(any("branch" in e for e in errors))


class TestEmptyPlan(unittest.TestCase):
    def test_empty_plan_is_valid(self):
        import execution_plan_schema as schema

        plan = schema.empty_plan()
        errors = schema.validate_plan(plan)
        self.assertEqual(errors, [])

    def test_empty_plan_has_required_fields(self):
        import execution_plan_schema as schema

        plan = schema.empty_plan()
        for field in ("title", "sources", "overview", "milestones"):
            self.assertIn(field, plan)


if __name__ == "__main__":
    unittest.main()
