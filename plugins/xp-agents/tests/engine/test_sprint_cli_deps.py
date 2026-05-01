#!/usr/bin/env python3
"""Tests for sprint_cli.py dependency-graph subcommands.

Split from test_sprint_cli.py at the commit that pushed it over the
500-line cap. Covers the two CLI surfaces that walk the sprint.json
dependency graph:

- `next-in-progress`: forward walk (which in-progress story has all
  deps satisfied?), powering /xp-story-close JIT branch creation.
- `find-transitive-dependents`: backward walk (which in-progress
  stories transitively depend on a given one?), powering /xp-accept
  cascade-deferral.
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

    def test_handles_malformed_story_id_gracefully(self):
        # If a sprint somehow contains a story id whose trailing segment
        # isn't all digits (e.g. a typo `story-2a` that escaped schema
        # validation, or a manually-edited sprint.json), the numeric
        # sort key must NOT raise an uncaught ValueError. Inside the
        # /xp-story-close pipeline a traceback here would be opaque;
        # graceful fallback to lexical ordering surfaces the bad id
        # without bringing down the close.
        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="in-progress", dependencies=[]),
                # Schema-bypass: feed sprint.json a typo'd id directly.
                _make_story(id="story-2a", status="in-progress"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(_CLI, ["next-in-progress"], self.smm_dir)
        # Must not crash with ValueError; must return *some* eligible id.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(result.stdout.strip(), {"story-001", "story-2a"})

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


class TestFindTransitiveDependentsCommand(_SMMTestCase):
    """CLI surface for cascade-deferral: print space-separated descendants."""

    def test_no_dependents_prints_empty(self):
        sprint = _make_sprint(
            stories=[_make_story(id="story-001", status="in-progress")]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI, ["find-transitive-dependents", "story-001"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_transitive_dependents_printed_space_separated(self):
        sprint = _make_sprint(
            stories=[
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
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        result = run_cli(
            _CLI, ["find-transitive-dependents", "story-001"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "story-002 story-003")


if __name__ == "__main__":
    unittest.main()
