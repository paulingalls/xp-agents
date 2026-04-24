#!/usr/bin/env python3
"""Tests for execution_plan_schema.py and execution_plan_store.py.

Covers: schema validation, load/save, has_remaining_work, count_milestones,
archive, render_markdown.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import VALID_SOURCE as _VALID_SOURCE
from conftest import _SMMTestCase
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan

# ===========================================================================
# Schema validation tests
# ===========================================================================


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
        # delivered requires delivered_sprint
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


# ===========================================================================
# Store tests
# ===========================================================================


class TestLoadPlan(_SMMTestCase):
    def test_load_valid_plan(self):
        import execution_plan_store as store

        plan = _make_plan()
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        loaded = store.load_plan(self.smm_dir)
        self.assertEqual(loaded["title"], "Test Plan")

    def test_load_missing_returns_none(self):
        import execution_plan_store as store

        result = store.load_plan(self.smm_dir)
        self.assertIsNone(result)

    def test_load_symlink_raises(self):
        import execution_plan_store as store

        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_make_plan()))
        link = self.smm_dir / "execution_plan.json"
        link.symlink_to(real)
        with self.assertRaises(OSError):
            store.load_plan(self.smm_dir)

    def test_load_corrupt_json_raises(self):
        import execution_plan_store as store

        (self.smm_dir / "execution_plan.json").write_text("{invalid json")
        with self.assertRaises(ValueError):
            store.load_plan(self.smm_dir)

    def test_load_invalid_schema_raises(self):
        import execution_plan_store as store

        (self.smm_dir / "execution_plan.json").write_text('{"bad": "schema"}')
        with self.assertRaises(ValueError):
            store.load_plan(self.smm_dir)


class TestSavePlan(_SMMTestCase):
    def test_save_valid_plan(self):
        import execution_plan_store as store

        plan = _make_plan()
        store.save_plan(self.smm_dir, plan)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["title"], "Test Plan")

    def test_save_invalid_plan_raises(self):
        import execution_plan_store as store

        with self.assertRaises(ValueError):
            store.save_plan(self.smm_dir, {"bad": "schema"})

    def test_save_clears_marker(self):
        import execution_plan_store as store

        marker = self.smm_dir / ".needs-execution-plan"
        marker.write_text("startup")
        store.save_plan(self.smm_dir, _make_plan())
        self.assertFalse(marker.exists())

    def test_save_symlink_raises(self):
        import execution_plan_store as store

        real = self.smm_dir / "real.json"
        real.write_text("{}")
        link = self.smm_dir / "execution_plan.json"
        link.symlink_to(real)
        with self.assertRaises(OSError):
            store.save_plan(self.smm_dir, _make_plan())


class TestUpdateMilestoneStatus(_SMMTestCase):
    """Tests for execution_plan_store.update_milestone_status()."""

    def _write_plan(self, milestones: list[dict]) -> None:
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=milestones))
        )

    def test_sets_in_progress(self):
        import execution_plan_store as store

        self._write_plan([_make_milestone(number=1, status="planned")])
        store.update_milestone_status(self.smm_dir, 1, "in-progress")
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "in-progress")

    def test_sets_delivered_with_sprint(self):
        import execution_plan_store as store

        self._write_plan([_make_milestone(number=1, status="in-progress")])
        store.update_milestone_status(
            self.smm_dir, 1, "delivered", delivered_sprint="sprint-003"
        )
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "delivered")
        self.assertEqual(loaded["milestones"][0]["delivered_sprint"], "sprint-003")

    def test_delivered_without_sprint_raises(self):
        import execution_plan_store as store

        self._write_plan([_make_milestone(number=1, status="in-progress")])
        with self.assertRaises(ValueError):
            store.update_milestone_status(self.smm_dir, 1, "delivered")

    def test_reverting_delivered_clears_delivered_sprint(self):
        """Transitioning away from 'delivered' clears delivered_sprint so the
        plan stays schema-valid (delivered requires a sprint; non-delivered
        must have delivered_sprint=None)."""
        import execution_plan_store as store

        self._write_plan(
            [
                _make_milestone(
                    number=1, status="delivered", delivered_sprint="sprint-003"
                )
            ]
        )
        store.update_milestone_status(self.smm_dir, 1, "planned")
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "planned")
        self.assertIsNone(loaded["milestones"][0]["delivered_sprint"])

    def test_no_plan_raises(self):
        import execution_plan_store as store

        with self.assertRaises(ValueError):
            store.update_milestone_status(self.smm_dir, 1, "in-progress")

    def test_unknown_milestone_raises(self):
        import execution_plan_store as store

        self._write_plan([_make_milestone(number=1, status="planned")])
        with self.assertRaises(ValueError):
            store.update_milestone_status(self.smm_dir, 99, "in-progress")


class TestHasRemainingWork(_SMMTestCase):
    def test_planned_milestones_have_remaining(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="planned")])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertTrue(store.has_remaining_work(self.smm_dir))

    def test_in_progress_milestones_have_remaining(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="in-progress")])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertTrue(store.has_remaining_work(self.smm_dir))

    def test_all_delivered_no_remaining(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(status="delivered", delivered_sprint="sprint-001")
            ]
        )
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertFalse(store.has_remaining_work(self.smm_dir))

    def test_missing_file_no_remaining(self):
        import execution_plan_store as store

        self.assertFalse(store.has_remaining_work(self.smm_dir))

    def test_mixed_statuses_has_remaining(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    number=1, status="delivered", delivered_sprint="sprint-001"
                ),
                _make_milestone(number=2, status="planned"),
            ]
        )
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertTrue(store.has_remaining_work(self.smm_dir))

    def test_deferred_does_not_count_as_remaining(self):
        """Deferred = consciously dropped, not pending. Same terminal class as
        delivered for the purpose of `is the plan complete?`."""
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="deferred")])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertFalse(store.has_remaining_work(self.smm_dir))

    def test_all_delivered_or_deferred_no_remaining(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    number=1, status="delivered", delivered_sprint="sprint-001"
                ),
                _make_milestone(number=2, status="deferred"),
            ]
        )
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        self.assertFalse(store.has_remaining_work(self.smm_dir))


class TestCountMilestones(_SMMTestCase):
    def test_count_all_statuses(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(number=1, status="planned"),
                _make_milestone(number=2, status="in-progress"),
                _make_milestone(
                    number=3, status="delivered", delivered_sprint="sprint-001"
                ),
                _make_milestone(
                    number=4, status="delivered", delivered_sprint="sprint-002"
                ),
            ]
        )
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        counts = store.count_milestones(self.smm_dir)
        self.assertEqual(counts["planned"], 1)
        self.assertEqual(counts["in-progress"], 1)
        self.assertEqual(counts["delivered"], 2)

    def test_count_missing_file(self):
        import execution_plan_store as store

        counts = store.count_milestones(self.smm_dir)
        self.assertEqual(counts["planned"], 0)
        self.assertEqual(counts["in-progress"], 0)
        self.assertEqual(counts["delivered"], 0)
        self.assertEqual(counts["deferred"], 0)

    def test_count_includes_deferred(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(number=1, status="planned"),
                _make_milestone(number=2, status="deferred"),
                _make_milestone(number=3, status="deferred"),
            ]
        )
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        counts = store.count_milestones(self.smm_dir)
        self.assertEqual(counts["planned"], 1)
        self.assertEqual(counts["deferred"], 2)


class TestArchive(_SMMTestCase):
    def test_archive_moves_to_plans_dir(self):
        import execution_plan_store as store

        plan = _make_plan()
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        archived_path = store.archive(self.smm_dir)
        self.assertFalse((self.smm_dir / "execution_plan.json").exists())
        self.assertTrue(archived_path.exists())
        self.assertTrue(archived_path.parent.name == "plans")

    def test_archive_missing_file_returns_none(self):
        import execution_plan_store as store

        result = store.archive(self.smm_dir)
        self.assertIsNone(result)

    def test_archive_preserves_content(self):
        import execution_plan_store as store

        plan = _make_plan(title="Archived Plan")
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        archived_path = store.archive(self.smm_dir)
        loaded = json.loads(archived_path.read_text())
        self.assertEqual(loaded["title"], "Archived Plan")


class TestRenderMarkdown(_SMMTestCase):
    def test_render_includes_title(self):
        import execution_plan_store as store

        plan = _make_plan(title="My Plan")
        md = store.render_markdown(plan)
        self.assertIn("# Execution Plan: My Plan", md)

    def test_render_includes_milestone(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[_make_milestone(name="Foundation", status="planned")]
        )
        md = store.render_markdown(plan)
        self.assertIn("### Milestone 1: Foundation [planned]", md)

    def test_render_includes_sources_table(self):
        import execution_plan_store as store

        plan = _make_plan()
        md = store.render_markdown(plan)
        self.assertIn("Design doc", md)
        self.assertIn("docs/design.md", md)

    def test_render_delivered_milestone_shows_sprint(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(status="delivered", delivered_sprint="sprint-003")
            ]
        )
        md = store.render_markdown(plan)
        self.assertIn("[delivered: sprint-003]", md)

    def test_render_includes_change_zones(self):
        import execution_plan_store as store

        plan = _make_plan()
        md = store.render_markdown(plan)
        self.assertIn("src/foo.py", md)
        self.assertIn("new module", md)

    def test_render_includes_branch_when_set(self):
        import execution_plan_store as store

        plan = _make_plan(branch="paulingalls/plan-foo")
        md = store.render_markdown(plan)
        self.assertIn("**Branch:** paulingalls/plan-foo", md)

    def test_render_omits_branch_line_when_null(self):
        import execution_plan_store as store

        plan = _make_plan(branch=None)
        md = store.render_markdown(plan)
        self.assertNotIn("**Branch:**", md)

    def test_render_omits_branch_line_when_absent(self):
        import execution_plan_store as store

        plan = _make_plan()
        self.assertNotIn("branch", plan)
        md = store.render_markdown(plan)
        self.assertNotIn("**Branch:**", md)

    def test_render_branch_appears_before_sources_table(self):
        """Branch lives directly under the title, above the Sources table."""
        import execution_plan_store as store

        plan = _make_plan(branch="user/plan-x")
        md = store.render_markdown(plan)
        self.assertLess(md.index("**Branch:**"), md.index("## Sources"))


class TestPlanExists(_SMMTestCase):
    def test_exists_when_file_present(self):
        import execution_plan_store as store

        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        self.assertTrue(store.plan_exists(self.smm_dir))

    def test_not_exists_when_missing(self):
        import execution_plan_store as store

        self.assertFalse(store.plan_exists(self.smm_dir))

    def test_not_exists_when_symlink(self):
        import execution_plan_store as store

        real = self.smm_dir / "real.json"
        real.write_text("{}")
        link = self.smm_dir / "execution_plan.json"
        link.symlink_to(real)
        self.assertFalse(store.plan_exists(self.smm_dir))


if __name__ == "__main__":
    unittest.main()
