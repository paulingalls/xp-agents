#!/usr/bin/env python3
"""Tests for sprint_cli.py: CLI wrapper for sprint operations."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"

_VALID_STORY = {
    "id": "story-001",
    "title": "User registration",
    "status": "ready",
    "size": "M",
    "dependencies": [],
    "milestone_ref": "",
    "design_sources": "",
    "context": "Build registration.",
    "file_domain": [],
    "interface_contracts": [],
    "acceptance_criteria": ["Users can register"],
}


def _make_sprint(**overrides) -> dict:
    plan = {
        "sprint_id": "sprint-001",
        "goal": "Build auth",
        "started": "2026-04-10",
        "milestone": "",
        "stories": [_VALID_STORY.copy()],
    }
    plan.update(overrides)
    return plan


def _make_story(**overrides) -> dict:
    s = _VALID_STORY.copy()
    s.update(overrides)
    return s


def _run_cli(
    args: list[str],
    smm_dir: Path,
    stdin_data: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_CLI),
        "--smm-dir",
        str(smm_dir),
        *args,
    ]
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestExistsCommand(_SMMTestCase):
    def test_exists(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = _run_cli(["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists(self):
        result = _run_cli(["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestHasActiveCommand(_SMMTestCase):
    def test_active_when_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = _run_cli(["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_no_active_when_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = _run_cli(["has-active"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestIsCompleteCommand(_SMMTestCase):
    def test_complete_when_all_done(self):
        sprint = _make_sprint(stories=[_make_story(status="done")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = _run_cli(["is-complete"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_complete_with_ready(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = _run_cli(["is-complete"], self.smm_dir)
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
        result = _run_cli(["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ready=1", result.stdout)
        self.assertIn("done=1", result.stdout)


class TestCreateCommand(_SMMTestCase):
    def test_create(self):
        sprint = _make_sprint(goal="New Sprint")
        result = _run_cli(["create"], self.smm_dir, json.dumps(sprint))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "sprint.json").exists())

    def test_create_invalid(self):
        result = _run_cli(["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryCommand(_SMMTestCase):
    def test_update_status(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = _run_cli(
            ["update-story", "story-001", "in-progress"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "in-progress")

    def test_invalid_story_id(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = _run_cli(["update-story", "story-999", "done"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestRenderCommand(_SMMTestCase):
    def test_render(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(goal="My Sprint"))
        )
        result = _run_cli(["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("# Sprint: My Sprint", result.stdout)

    def test_render_missing(self):
        result = _run_cli(["render"], self.smm_dir)
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
        result = _run_cli(["render-stories", "story-001"], self.smm_dir)
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
        result = _run_cli(["velocity"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("delivered=1", result.stdout)
        self.assertIn("carried=1", result.stdout)


class TestAddStoryCommand(_SMMTestCase):
    def test_add_story(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        new_story = _make_story(id="story-002", title="Login")
        result = _run_cli(
            ["add-story"],
            self.smm_dir,
            json.dumps(new_story),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 2)


if __name__ == "__main__":
    unittest.main()
