#!/usr/bin/env python3
"""Tests for sprint_store.py — load/save, mutations, render.

Covers: load/save, update_story_status, set_branch, set_story_branch,
render_markdown, render_story_sections. Status checks (has_active_*,
is_complete, scheduled_*), compute_velocity, compute_blockers, and
count_by_status live in test_sprint_status.py (split for the 500-line
cap). Schema validation tests live in test_sprint_schema.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

# ===========================================================================
# Store load/save tests
# ===========================================================================


class TestLoadSprint(_SMMTestCase):
    def test_load_valid(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        loaded = sprint_store.load_sprint(self.smm_dir)
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_load_missing_returns_none(self):
        import sprint_store

        self.assertIsNone(sprint_store.load_sprint(self.smm_dir))

    def test_load_symlink_raises(self):
        import sprint_store

        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_make_sprint()))
        (self.smm_dir / "sprint.json").symlink_to(real)
        with self.assertRaises(OSError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_corrupt_json_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text("{bad json")
        with self.assertRaises(ValueError):
            sprint_store.load_sprint(self.smm_dir)

    def test_load_invalid_schema_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text('{"bad": "schema"}')
        with self.assertRaises(ValueError):
            sprint_store.load_sprint(self.smm_dir)


class TestSaveSprint(_SMMTestCase):
    def test_save_valid(self):
        import sprint_store

        sprint_store.save_sprint(self.smm_dir, _make_sprint())
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_save_invalid_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.save_sprint(self.smm_dir, {"bad": "data"})

    def test_save_clears_needs_sprint_marker(self):
        import sprint_store

        marker = self.smm_dir / ".needs-sprint"
        marker.write_text("startup")
        sprint_store.save_sprint(self.smm_dir, _make_sprint())
        self.assertFalse(marker.exists())

    def test_save_keeps_marker_when_no_active(self):
        import sprint_store

        marker = self.smm_dir / ".needs-sprint"
        marker.write_text("startup")
        sprint = _make_sprint(stories=[_make_story(status="done")])
        sprint_store.save_sprint(self.smm_dir, sprint)
        self.assertTrue(marker.exists())


# ===========================================================================
# Update story status
# ===========================================================================


class TestUpdateStoryStatus(_SMMTestCase):
    def test_update_to_in_progress(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.update_story_status(self.smm_dir, "story-001", "in-progress")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_update_to_done(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "done")

    def test_invalid_story_id_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        with self.assertRaises(ValueError):
            sprint_store.update_story_status(self.smm_dir, "story-999", "done")

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.update_story_status(self.smm_dir, "story-001", "done")


class TestSetBranch(_SMMTestCase):
    def test_writes_branch_name(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.set_branch(self.smm_dir, "paul/sprint-031-test")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["branch_name"], "paul/sprint-031-test")

    def test_overwrites_existing(self):
        import sprint_store

        sprint = _make_sprint(branch_name="old/name")
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        sprint_store.set_branch(self.smm_dir, "new/name")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["branch_name"], "new/name")

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.set_branch(self.smm_dir, "paul/sprint-031-test")


class TestSetStoryBranch(_SMMTestCase):
    def test_writes_story_branch_name(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        sprint_store.set_story_branch(self.smm_dir, "story-001", "paul/story-001-foo")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "paul/story-001-foo")

    def test_overwrites_existing(self):
        import sprint_store

        story = _make_story(branch_name="old/branch")
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[story]))
        )
        sprint_store.set_story_branch(self.smm_dir, "story-001", "new/branch")
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "new/branch")

    def test_invalid_story_id_raises(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        with self.assertRaises(ValueError):
            sprint_store.set_story_branch(
                self.smm_dir, "story-999", "paul/story-999-foo"
            )

    def test_no_sprint_raises(self):
        import sprint_store

        with self.assertRaises(ValueError):
            sprint_store.set_story_branch(
                self.smm_dir, "story-001", "paul/story-001-foo"
            )


# Status check functions, compute_velocity, compute_blockers, count_by_status
# tests live in test_sprint_status.py — split per the 500-line cap. Render
# and load/save tests stay here.


# ===========================================================================
# Render
# ===========================================================================


class TestRenderMarkdown(unittest.TestCase):
    def test_render_includes_goal(self):
        import sprint_store

        md = sprint_store.render_markdown(_make_sprint(goal="Build auth"))
        self.assertIn("# Sprint: Build auth", md)

    def test_render_includes_story(self):
        import sprint_store

        md = sprint_store.render_markdown(_make_sprint())
        self.assertIn("### story-001: User registration", md)
        self.assertIn("**Status:** ready", md)

    def test_render_includes_sprint_id(self):
        import sprint_store

        md = sprint_store.render_markdown(_make_sprint())
        self.assertIn("sprint-001", md)

    def test_render_acceptance_execution(self):
        import sprint_store

        ae = {
            "type": "pytest",
            "command": "pytest tests/acceptance/",
            "setup": "docker compose up -d",
            "notes": "Requires backend on :3000",
        }
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        md = sprint_store.render_markdown(sprint)
        self.assertIn("**Acceptance Execution:**", md)
        self.assertIn("**Type:** pytest", md)
        self.assertIn("`pytest tests/acceptance/`", md)
        self.assertIn("`docker compose up -d`", md)
        self.assertIn("Requires backend on :3000", md)

    def test_render_acceptance_execution_minimal(self):
        import sprint_store

        ae = {"type": "bash", "command": "bash test.sh"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        md = sprint_store.render_markdown(sprint)
        self.assertIn("**Type:** bash", md)
        self.assertIn("`bash test.sh`", md)
        self.assertNotIn("**Setup:**", md)
        self.assertNotIn("**Notes:**", md)

    def test_render_no_acceptance_execution(self):
        import sprint_store

        md = sprint_store.render_markdown(_make_sprint())
        self.assertNotIn("Acceptance Execution", md)


class TestRenderStorySections(unittest.TestCase):
    def test_render_specific_stories(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", title="First"),
                _make_story(id="story-002", title="Second"),
                _make_story(id="story-003", title="Third"),
            ]
        )
        md = sprint_store.render_story_sections(sprint, ["story-001", "story-003"])
        self.assertIn("story-001", md)
        self.assertIn("First", md)
        self.assertIn("story-003", md)
        self.assertIn("Third", md)
        self.assertNotIn("story-002", md)

    def test_empty_ids_returns_empty(self):
        import sprint_store

        md = sprint_store.render_story_sections(_make_sprint(), [])
        self.assertEqual(md, "")


class TestTransitiveInProgressDependents(_SMMTestCase):
    """Return sorted in-progress stories transitively blocked by a given story."""

    def _write(self, *stories: dict) -> None:
        sprint = _make_sprint(stories=list(stories))
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_no_sprint_returns_empty(self):
        import sprint_store

        result = sprint_store.transitive_in_progress_dependents(
            self.smm_dir, "story-001"
        )
        self.assertEqual(result, [])

    def test_no_dependents_returns_empty(self):
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(id="story-002", status="in-progress"),
        )
        result = sprint_store.transitive_in_progress_dependents(
            self.smm_dir, "story-001"
        )
        self.assertEqual(result, [])

    def test_direct_in_progress_dependent_returned(self):
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_in_progress_dependents(self.smm_dir, "story-001"),
            ["story-002"],
        )

    def test_transitive_in_progress_dependents_returned_sorted(self):
        import sprint_store

        # story-001 → story-002 → story-003; all in-progress.
        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001"],
            ),
            _make_story(
                id="story-003",
                status="in-progress",
                dependencies=["story-002"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_in_progress_dependents(self.smm_dir, "story-001"),
            ["story-002", "story-003"],
        )

    def test_done_dependent_excluded(self):
        # A done dependent has already shipped — no need to defer it. The
        # transitive walk must filter by status, not by dependency edge alone.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(id="story-002", status="done", dependencies=["story-001"]),
        )
        self.assertEqual(
            sprint_store.transitive_in_progress_dependents(self.smm_dir, "story-001"),
            [],
        )

    def test_dependency_cycle_terminates(self):
        # Sprint schema doesn't enforce DAG; a cycle (story depending on
        # itself, or A↔B) must not infinite-loop the walker. Real cycles
        # come from copy-paste typos in sprint.json.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001", "story-002"],
            ),
        )
        result = sprint_store.transitive_in_progress_dependents(
            self.smm_dir, "story-001"
        )
        self.assertEqual(result, ["story-002"])


if __name__ == "__main__":
    unittest.main()
