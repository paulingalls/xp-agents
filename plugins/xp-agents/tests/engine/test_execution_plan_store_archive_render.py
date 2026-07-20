#!/usr/bin/env python3
"""Tests for execution_plan_store.py — archive, render_markdown, plan_exists.

Split from test_execution_plan_store.py for the 500-line cap.
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

    def test_render_includes_surfaces_touched(self):
        import execution_plan_store as store

        plan = _make_plan(milestones=[_make_milestone(surfaces_touched=["api", "cli"])])
        md = store.render_markdown(plan)
        self.assertIn("Surfaces Touched", md)
        self.assertIn("api, cli", md)

    def test_render_omits_surfaces_touched_when_absent(self):
        import execution_plan_store as store

        md = store.render_markdown(_make_plan())
        self.assertNotIn("Surfaces Touched", md)

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
