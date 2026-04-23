#!/usr/bin/env python3
"""Tests for sprint_schema.py and sprint_store.py.

Covers: schema validation, load/save, update_story_status, status checks,
compute_velocity, compute_blockers, render_markdown, render_story_sections.
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
# Schema tests
# ===========================================================================


class TestValidateSprint(unittest.TestCase):
    def test_valid_sprint_no_errors(self):
        import sprint_schema

        errors = sprint_schema.validate_sprint(_make_sprint())
        self.assertEqual(errors, [])

    def test_not_a_dict(self):
        import sprint_schema

        errors = sprint_schema.validate_sprint("not a dict")
        self.assertIn("must be an object", errors[0])

    def test_missing_required_fields(self):
        import sprint_schema

        errors = sprint_schema.validate_sprint({})
        for field in ("sprint_id", "goal", "started", "stories"):
            self.assertTrue(
                any(field in e for e in errors),
                f"Missing error for {field}",
            )

    def test_invalid_story_status(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(status="bogus")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("status" in e for e in errors))

    def test_valid_statuses(self):
        import sprint_schema

        for status in ("ready", "in-progress", "done", "deferred"):
            sprint = _make_sprint(stories=[_make_story(status=status)])
            errors = sprint_schema.validate_sprint(sprint)
            self.assertEqual(errors, [], f"Status {status!r} should be valid")

    def test_story_missing_required_fields(self):
        import sprint_schema

        sprint = _make_sprint(stories=[{"id": "story-001"}])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertGreater(len(errors), 0)

    def test_stories_must_be_list(self):
        import sprint_schema

        errors = sprint_schema.validate_sprint(_make_sprint(stories="not list"))
        self.assertTrue(any("stories" in e for e in errors))

    def test_acceptance_execution_valid(self):
        import sprint_schema

        ae = {"type": "pytest", "command": "pytest tests/acceptance/"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_with_all_fields(self):
        import sprint_schema

        ae = {
            "type": "playwright",
            "command": "npx playwright test",
            "setup": "docker compose up -d",
            "notes": "Requires backend on :3000",
        }
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_absent_is_valid(self):
        import sprint_schema

        sprint = _make_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_missing_type_fails(self):
        import sprint_schema

        ae = {"command": "pytest tests/"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("type" in e for e in errors))

    def test_acceptance_execution_missing_command_fails(self):
        import sprint_schema

        ae = {"type": "pytest"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("command" in e for e in errors))

    def test_acceptance_execution_not_dict_fails(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(acceptance_execution="bad")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("acceptance_execution" in e for e in errors))


class TestEmptySprint(unittest.TestCase):
    def test_empty_sprint_is_valid(self):
        import sprint_schema

        sprint = sprint_schema.empty_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_has_required_fields(self):
        import sprint_schema

        sprint = sprint_schema.empty_sprint()
        for field in ("sprint_id", "goal", "started", "stories"):
            self.assertIn(field, sprint)


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


# ===========================================================================
# Status check functions
# ===========================================================================


class TestStatusChecks(_SMMTestCase):
    def test_has_active_stories_ready(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        self.assertTrue(sprint_store.has_active_stories(self.smm_dir))

    def test_has_active_stories_in_progress(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_active_stories(self.smm_dir))

    def test_no_active_when_all_done(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.has_active_stories(self.smm_dir))

    def test_no_active_when_missing(self):
        import sprint_store

        self.assertFalse(sprint_store.has_active_stories(self.smm_dir))

    def test_is_complete_all_done(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="deferred"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.is_complete(self.smm_dir))

    def test_not_complete_with_ready(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        self.assertFalse(sprint_store.is_complete(self.smm_dir))

    def test_has_in_progress(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_in_progress_stories(self.smm_dir))

    def test_has_ready(self):
        import sprint_store

        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        self.assertTrue(sprint_store.has_ready_stories(self.smm_dir))

    def test_sprint_exists(self):
        import sprint_store

        self.assertFalse(sprint_store.sprint_exists(self.smm_dir))
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        self.assertTrue(sprint_store.sprint_exists(self.smm_dir))


# ===========================================================================
# Computed fields
# ===========================================================================


class TestComputeVelocity(unittest.TestCase):
    def test_velocity(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="done"),
                _make_story(id="s3", status="deferred"),
                _make_story(id="s4", status="ready"),
            ]
        )
        v = sprint_store.compute_velocity(sprint)
        self.assertEqual(v["stories_planned"], 4)
        self.assertEqual(v["stories_delivered"], 2)
        self.assertEqual(v["stories_carried"], 1)


class TestComputeBlockers(unittest.TestCase):
    def test_blocker_detected(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="ready",
                    dependencies=["story-002"],
                ),
                _make_story(id="story-002", status="in-progress"),
            ]
        )
        blockers = sprint_store.compute_blockers(sprint)
        self.assertEqual(len(blockers), 1)
        self.assertIn("story-001", blockers[0])

    def test_no_blocker_when_dep_done(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="ready",
                    dependencies=["story-002"],
                ),
                _make_story(id="story-002", status="done"),
            ]
        )
        blockers = sprint_store.compute_blockers(sprint)
        self.assertEqual(len(blockers), 0)

    def test_no_deps_no_blockers(self):
        import sprint_store

        blockers = sprint_store.compute_blockers(_make_sprint())
        self.assertEqual(len(blockers), 0)


class TestCountByStatus(unittest.TestCase):
    def test_counts(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="ready"),
                _make_story(id="s2", status="in-progress"),
                _make_story(id="s3", status="done"),
                _make_story(id="s4", status="deferred"),
            ]
        )
        counts = sprint_store.count_by_status(sprint)
        self.assertEqual(counts["ready"], 1)
        self.assertEqual(counts["in-progress"], 1)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["deferred"], 1)


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


if __name__ == "__main__":
    unittest.main()
