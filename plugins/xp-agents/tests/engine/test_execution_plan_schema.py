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


class TestSurfacesTouched(unittest.TestCase):
    """milestone.surfaces_touched: optional list[str], FK to
    acceptance_surfaces[*].name when a valid_surfaces set is supplied."""

    def test_absent_surfaces_touched_valid(self):
        import execution_plan_schema as schema

        self.assertEqual(schema.validate_plan(_make_plan()), [])

    def test_known_surfaces_with_valid_set_pass(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(surfaces_touched=["api", "cli"])])
        errors = schema.validate_plan(plan, valid_surfaces=frozenset({"api", "cli"}))
        self.assertEqual(errors, [])

    def test_unknown_surface_with_valid_set_reports_fk_error(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[_make_milestone(surfaces_touched=["api", "ghost"])]
        )
        errors = schema.validate_plan(plan, valid_surfaces=frozenset({"api"}))
        self.assertTrue(
            any("surfaces_touched" in e and "ghost" in e for e in errors), errors
        )

    def test_unknown_surface_without_valid_set_is_shape_only(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(surfaces_touched=["anything"])])
        self.assertEqual(schema.validate_plan(plan), [])

    def test_non_list_surfaces_touched_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(surfaces_touched="api")])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("surfaces_touched" in e for e in errors), errors)

    def test_non_string_surface_entry_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(surfaces_touched=["api", 7])])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("surfaces_touched" in e for e in errors), errors)


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


class TestMilestoneSchedules(unittest.TestCase):
    """`schedules` — the structural link from a milestone to the recorded items
    it schedules (a debt/concern id), replacing prose inference.

    It lives on the MILESTONE, not the zone, on purpose: `_validate_zone_entry`
    is shared by `change_zones` AND `impact_zones`, so a zone-level field would
    silently land on impact zones too — and an impact-zone ref means "touched",
    not "scheduled", the exact confusion this field exists to end.
    """

    def test_milestone_with_schedules_is_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(schedules=["4ecd48c71327"])])
        self.assertEqual(schema.validate_plan(plan), [])

    def test_milestone_without_schedules_is_valid(self):
        """Optional — every plan authored before this field must stay valid."""
        import execution_plan_schema as schema

        milestone = _make_milestone()
        self.assertNotIn("schedules", milestone)
        self.assertEqual(schema.validate_plan(_make_plan(milestones=[milestone])), [])

    def test_empty_schedules_is_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(schedules=[])])
        self.assertEqual(schema.validate_plan(plan), [])

    def test_malformed_id_is_rejected(self):
        import execution_plan_schema as schema

        # "4ecd48c71327\n" is the one that bites: ids are consumed by exact
        # string equality, so a newline-suffixed id that VALIDATES then matches
        # no debt at all — the retro escalates work the plan already schedules.
        for bad in (
            "not-an-id",
            "ABCDEF123456",
            "4ecd48c7132",
            "4ecd48c713277",
            "4ecd48c71327\n",
        ):
            with self.subTest(bad=bad):
                plan = _make_plan(milestones=[_make_milestone(schedules=[bad])])
                errors = schema.validate_plan(plan)
                self.assertTrue(
                    any("schedules[0]" in e for e in errors),
                    f"{bad!r} is not a 12-hex event id but was accepted",
                )

    def test_non_string_entry_is_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(schedules=[123])])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("schedules[0]" in e for e in errors))

    def test_schedules_must_be_a_list(self):
        import execution_plan_schema as schema

        plan = _make_plan(milestones=[_make_milestone(schedules="4ecd48c71327")])
        errors = schema.validate_plan(plan)
        self.assertTrue(any("schedules" in e for e in errors))


class TestMilestoneAcceptanceExecutionPins(unittest.TestCase):
    """`acceptance_execution.pins` is a story-scoped verify-gate exemption:
    scripts/verify_paths.extract_verify_paths(story) is the only consumer,
    and it is only ever called with a STORY dict (close_verify_gate.py,
    verify_deferred.py) — never a milestone. A milestone-level `pins` list
    used to pass schema validation and then silently do nothing (no
    milestone-scoped verify gate exists to read it), which is a trap for a
    plan author who reasonably expects it to work like the story-level
    field. The schema now rejects it outright so the author learns at
    plan-validate time instead of never.
    """

    def test_milestone_acceptance_execution_with_pins_is_rejected(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    acceptance_execution={
                        "type": "automated",
                        "command": "pytest tests/",
                        "pins": ["tests/regression_test.py"],
                    }
                )
            ]
        )
        errors = schema.validate_plan(plan)
        self.assertTrue(
            any(
                "acceptance_execution.pins" in e and "story-scoped" in e for e in errors
            ),
            f"expected a story-scoped pins rejection, got {errors}",
        )

    def test_milestone_acceptance_execution_without_pins_is_valid(self):
        import execution_plan_schema as schema

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    acceptance_execution={
                        "type": "automated",
                        "command": "pytest tests/",
                    }
                )
            ]
        )
        self.assertEqual(schema.validate_plan(plan), [])


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
