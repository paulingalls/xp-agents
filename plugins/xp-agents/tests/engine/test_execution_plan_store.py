#!/usr/bin/env python3
"""Tests for execution_plan_store.py — load/save, queries, archive, render.

Schema validation tests live in test_execution_plan_schema.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase
from conftest import make_milestone_dict as _make_milestone
from conftest import make_plan_dict as _make_plan


class TestLoadPlan(_SMMTestCase):
    def test_load_valid_plan(self):
        import execution_plan_store as store

        plan = _make_plan()
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        loaded = store.load_plan(self.smm_dir)
        assert loaded is not None
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


class TestPlanIsComplete(unittest.TestCase):
    """Pure helper: is every milestone in a terminal status?"""

    def test_all_delivered_is_complete(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(status="delivered", delivered_sprint="sprint-001")
            ]
        )
        self.assertTrue(store.plan_is_complete(plan))

    def test_all_deferred_is_complete(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="deferred")])
        self.assertTrue(store.plan_is_complete(plan))

    def test_mix_delivered_and_deferred_is_complete(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[
                _make_milestone(
                    number=1, status="delivered", delivered_sprint="sprint-001"
                ),
                _make_milestone(number=2, status="deferred"),
            ]
        )
        self.assertTrue(store.plan_is_complete(plan))

    def test_planned_milestone_is_incomplete(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="planned")])
        self.assertFalse(store.plan_is_complete(plan))

    def test_in_progress_milestone_is_incomplete(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="in-progress")])
        self.assertFalse(store.plan_is_complete(plan))

    def test_empty_milestones_is_complete(self):
        """No milestones means no remaining work — trivially complete."""
        import execution_plan_store as store

        plan = _make_plan(milestones=[])
        self.assertTrue(store.plan_is_complete(plan))


class TestArchive(_SMMTestCase):
    def test_archive_moves_to_plans_dir(self):
        import execution_plan_store as store

        plan = _make_plan()
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        archived_path = store.archive(self.smm_dir)
        assert archived_path is not None
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
        assert archived_path is not None
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

    def test_render_deferred_milestone_shows_deferred_tag(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[_make_milestone(name="Skipped feature", status="deferred")]
        )
        md = store.render_markdown(plan)
        self.assertIn("### Milestone 1: Skipped feature [deferred]", md)

    def test_render_deferred_does_not_show_sprint(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(status="deferred")])
        md = store.render_markdown(plan)
        self.assertIn("[deferred]", md)
        self.assertNotIn("[deferred:", md)


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
