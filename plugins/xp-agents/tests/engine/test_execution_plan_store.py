#!/usr/bin/env python3
"""Tests for execution_plan_store.py — load/save and milestone queries.

Schema validation tests live in test_execution_plan_schema.py. Archive and
render_markdown tests live in test_execution_plan_store_archive_render.py
(split for the 500-line cap).
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


class TestFindMilestone(unittest.TestCase):
    def test_find_returns_matching_milestone(self):
        import execution_plan_store as store

        plan = _make_plan(
            milestones=[_make_milestone(number=1), _make_milestone(number=3)]
        )
        found = store.find_milestone(plan, 3)
        assert found is not None
        self.assertEqual(found["number"], 3)

    def test_find_returns_none_when_absent(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(number=1)])
        self.assertIsNone(store.find_milestone(plan, 99))

    def test_find_required_returns_matching(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(number=2)])
        self.assertEqual(store.find_milestone_required(plan, 2)["number"], 2)

    def test_find_required_raises_when_absent(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(number=1)])
        with self.assertRaises(ValueError):
            store.find_milestone_required(plan, 99)


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


# Archive, render_markdown, and plan_exists tests live in
# test_execution_plan_store_archive_render.py — split for the 500-line cap.


if __name__ == "__main__":
    unittest.main()
