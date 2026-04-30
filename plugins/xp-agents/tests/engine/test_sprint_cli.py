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


class TestEditStoryCommand(_SMMTestCase):
    """edit-story updates arbitrary story fields via stdin JSON."""

    def test_updates_context_field(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "Updated context."}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["context"], "Updated context.")

    def test_unknown_story_id_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-999"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_validates_schema(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "x" * 601}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("budget", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"context": "new"}),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_id_override(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps({"id": "story-999"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immutable", result.stderr.lower())

    def test_rejects_non_object_input(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["edit-story", "story-001"],
            self.smm_dir,
            json.dumps(["not", "a", "dict"]),
        )
        self.assertNotEqual(result.returncode, 0)


class TestUpdateStoryBranch(_SMMTestCase):
    def test_sets_branch_name(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["branch_name"], "paul/story-001-foo")

    def test_invalid_story_fails(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-999", "paul/story-999-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", result.stderr.lower())

    def test_no_sprint_fails(self):
        result = run_cli(
            _CLI,
            ["update-story-branch", "story-001", "paul/story-001-foo"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)


class TestGetStoryBranchCommand(_SMMTestCase):
    """get-story-branch prints a story's recorded branch_name. Replaces
    the inline `python3 -c` JSON-poking that /xp-story-close was using
    in Step 8 to gate JIT-create on solo vs teammate (parallel) mode.
    """

    def test_returns_recorded_branch_name(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", branch_name="paul/story-001-foo"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "paul/story-001-foo")

    def test_returns_empty_when_unset(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_returns_empty_when_story_missing(self):
        sprint = _make_sprint(stories=[_make_story(id="story-001")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story-branch", "story-999"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_returns_empty_when_no_sprint(self):
        result = run_cli(_CLI, ["get-story-branch", "story-001"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class TestNextInProgressCommand(_SMMTestCase):
    """Tests for the next-in-progress subcommand. See sprint_store
    docstring for behavior; tests cover empty/no-sprint cases plus
    dep-satisfaction filtering and numeric id ordering."""

    def test_no_sprint_exits_one_with_empty_stdout(self):
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")

    def test_no_in_progress_exits_one(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="done"),
                _make_story(id="story-002", status="ready"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")

    def test_single_in_progress_no_deps_returned(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="in-progress", dependencies=[]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-001")

    def test_picks_lowest_id_when_multiple_eligible(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-002", status="in-progress", dependencies=[]),
                _make_story(id="story-001", status="in-progress", dependencies=[]),
                _make_story(id="story-003", status="in-progress", dependencies=[]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-001")

    def test_numeric_sort_beats_lexical(self):
        # story-2 < story-10 numerically, but lexical sort would pick
        # story-10. Guards the numeric-key sort in next_in_progress.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-10", status="in-progress", dependencies=[]),
                _make_story(id="story-2", status="in-progress", dependencies=[]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-2")

    def test_excludes_stories_with_unmet_deps(self):
        # story-002 depends on story-001 which is still in-progress
        # (not done). story-002 must NOT be returned even though it's
        # in-progress — its dep is not satisfied. story-001 IS returned.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="in-progress", dependencies=[]),
                _make_story(
                    id="story-002",
                    status="in-progress",
                    dependencies=["story-001"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-001")

    def test_excludes_dependent_of_deferred_story(self):
        # When an upstream story is deferred (e.g. cascade from a
        # failed AC), in-progress stories that depend on it must NOT
        # be returned — their dep is not "done". Validates the JIT-next
        # safety property the plan reviewer flagged.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="deferred", dependencies=[]),
                _make_story(
                    id="story-002",
                    status="in-progress",
                    dependencies=["story-001"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        # No story qualifies — story-002's dep is deferred, not done.
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
