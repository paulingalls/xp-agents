#!/usr/bin/env python3
"""Tests for sprint_cli.py read-only query subcommands.

The structural-mutation suites live in test_sprint_cli_mutate.py and the
validate-domain suite in test_sprint_cli_validate.py — split out in
sprint-108 M1 to keep each test file under the 500-line cap (decision
d027fe5c9066).
"""

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


class TestNextScheduledCommand(_SMMTestCase):
    def test_returns_first_scheduled_id(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="done"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-002")

    def test_no_scheduled_exits_nonzero(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_treat_as_done_satisfies_dep(self):
        # Mirrors xp-story-close Step 8: the just-closed story's
        # status is `closing` (not yet `done`), so a dep-gated next
        # story would be invisible without the override.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="closing"),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Without the flag: dep is `closing`, not `done` — exit 1.
        result = run_cli(_CLI, ["next-scheduled"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        # With the flag: dep treated as satisfied; story-002 surfaces.
        result = run_cli(
            _CLI,
            ["next-scheduled", "--treat-as-done", "story-001"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-002")

    def test_treat_as_done_accepts_multiple_ids(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="closing"),
                _make_story(id="story-002", status="closing"),
                _make_story(
                    id="story-003",
                    status="scheduled",
                    dependencies=["story-001", "story-002"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI,
            [
                "next-scheduled",
                "--treat-as-done",
                "story-001",
                "--treat-as-done",
                "story-002",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-003")


class TestScheduledOverlapCommand(_SMMTestCase):
    def test_overlap_exit0_when_shared_file(self):
        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["src/a.py — owner", "src/b.py — shared"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py — caller", "src/c.py — owner"],
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["scheduled-overlap"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overlap_exit1_when_disjoint(self):
        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="scheduled", file_domain=["a.py"]),
                _make_story(id="s2", status="scheduled", file_domain=["b.py"]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["scheduled-overlap"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestUpdateStoryAcceptsScheduled(_SMMTestCase):
    def test_update_story_to_scheduled(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["update-story", "story-001", "scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(loaded["stories"][0]["status"], "scheduled")


class TestCountStatusAcceptsScheduled(_SMMTestCase):
    def test_count_scheduled(self):
        sprint = _make_sprint(stories=[_make_story(status="scheduled")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["count-status", "scheduled"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")


class TestGetStoryCommand(_SMMTestCase):
    def test_get_story_returns_json(self):
        sprint = _make_sprint(
            stories=[_make_story(id="story-042", title="Demo", status="ready")]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["get-story", "story-042"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["id"], "story-042")
        self.assertEqual(story["title"], "Demo")
        self.assertEqual(story["status"], "ready")

    def test_get_story_missing_id_exits_nonzero(self):
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        result = run_cli(_CLI, ["get-story", "story-999"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_get_story_no_sprint_file_exits_nonzero(self):
        result = run_cli(_CLI, ["get-story", "story-001"], self.smm_dir)
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


class TestSprintCliHelp(_SMMTestCase):
    def test_help_contains_examples(self):
        result = run_cli(_CLI, ["--help"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Examples:", result.stdout)


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


class TestReadyFrontierCommand(_SMMTestCase):
    """ready-frontier emits JSON {"frontier": [...], "parallelizable": bool}
    for the /xp-schedule preload to consume. Exit 0 always — an empty
    frontier is a valid state, not an error."""

    def _run(self, stories, extra_args=None):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["ready-frontier", *(extra_args or [])], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_single_story_frontier_not_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001"])
        self.assertFalse(out["parallelizable"])

    def test_disjoint_multi_frontier_is_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001", "story-002"])
        self.assertTrue(out["parallelizable"])

    def test_overlapping_multi_frontier_not_parallelizable(self):
        out = self._run(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py — y"],
                ),
            ]
        )
        self.assertEqual(out["frontier"], ["story-001", "story-002"])
        self.assertFalse(out["parallelizable"])

    def test_empty_frontier(self):
        out = self._run([_make_story(id="story-001", status="done", dependencies=[])])
        self.assertEqual(out["frontier"], [])
        self.assertFalse(out["parallelizable"])

    def test_no_sprint_is_empty(self):
        result = run_cli(_CLI, ["ready-frontier"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "frontier": [],
                "parallelizable": False,
                "overlap": {"collisions": {}, "glob_forced": False},
            },
        )

    def test_treat_as_done_unblocks_frontier(self):
        out = self._run(
            [
                _make_story(id="story-001", status="closing", dependencies=[]),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
            ],
            extra_args=["--treat-as-done", "story-001"],
        )
        self.assertEqual(out["frontier"], ["story-002"])


if __name__ == "__main__":
    unittest.main()
