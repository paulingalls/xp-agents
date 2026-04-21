#!/usr/bin/env python3
"""Tests for sprint_cli.py: CLI wrapper for sprint operations."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


class TestExistsCommand(_SMMTestCase):
    def test_exists(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists(self):
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestHasActiveCommand(_SMMTestCase):
    def test_active_when_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_no_active_when_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestIsCompleteCommand(_SMMTestCase):
    def test_complete_when_all_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["is-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_complete_with_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["is-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestCountCommand(_SMMTestCase):
    def test_count_output(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="ready"),
                _make_story(id="s2", status="done"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ready=1", result.stdout)
        self.assertIn("done=1", result.stdout)


class TestCreateCommand(_SMMTestCase):
    def test_create(self):
        sprint = _make_sprint(goal="New Sprint")
        result = run_cli(_CLI, ["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())

    def test_create_invalid(self):
        result = run_cli(_CLI, ["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryCommand(_SMMTestCase):
    def test_update_status(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story", "story-001", "in-progress"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_invalid_story_id(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["update-story", "story-999", "done"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestRenderCommand(_SMMTestCase):
    def test_render(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(goal="My Sprint"))
        )
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("# Sprint: My Sprint", result.stdout)

    def test_render_missing(self):
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestRenderStoriesCommand(_SMMTestCase):
    def test_render_specific(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", title="First"),
                _make_story(id="story-002", title="Second"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["render-stories", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("First", result.stdout)
        self.assertNotIn("Second", result.stdout)


class TestVelocityCommand(_SMMTestCase):
    def test_velocity(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="deferred"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["velocity"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("delivered=1", result.stdout)
        self.assertIn("carried=1", result.stdout)


class TestAddStoryCommand(_SMMTestCase):
    def test_add_story(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        new_story = _make_story(id="story-002", title="Login")
        result = run_cli(
            _CLI,
            ["add-story"],
            self.smm_dir,
            json.dumps(new_story),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 2)


class TestSprintCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


class TestAssignStoryCommand(_SMMTestCase):
    """assign-story writes .story-assignment-{name} marker."""

    def test_writes_marker_file(self):
        result = run_cli(
            _CLI,
            ["assign-story", "story-001", "--name", "main"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / ".story-assignment-main"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text().strip(), "story-001")

    def test_rejects_symlink_target(self):
        target = self.smm_dir / "real-marker"
        target.write_text("old")
        link = self.smm_dir / ".story-assignment-main"
        link.symlink_to(target)
        result = run_cli(
            _CLI,
            ["assign-story", "story-001", "--name", "main"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_overwrites_existing(self):
        run_cli(
            _CLI,
            ["assign-story", "story-001", "--name", "main"],
            self.smm_dir,
        )
        run_cli(
            _CLI,
            ["assign-story", "story-002", "--name", "main"],
            self.smm_dir,
        )
        marker = self.smm_dir / ".story-assignment-main"
        self.assertEqual(marker.read_text().strip(), "story-002")

    def test_teammate_name(self):
        result = run_cli(
            _CLI,
            ["assign-story", "story-003", "--name", "teammate-step-1"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.smm_dir / ".story-assignment-teammate-step-1"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text().strip(), "story-003")


if __name__ == "__main__":
    unittest.main()
