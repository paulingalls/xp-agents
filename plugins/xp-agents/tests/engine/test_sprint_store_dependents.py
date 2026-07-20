#!/usr/bin/env python3
"""Tests for sprint_store.py — transitive_active_dependents.

Returns sorted in-motion stories transitively blocked by a given story.
Split from test_sprint_store.py for the 500-line cap.
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


class TestTransitiveActiveDependents(_SMMTestCase):
    """Return sorted in-motion stories transitively blocked by a given story."""

    def _write(self, *stories: dict) -> None:
        sprint = _make_sprint(stories=list(stories))
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_no_sprint_returns_empty(self):
        import sprint_store

        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
        self.assertEqual(result, [])

    def test_no_dependents_returns_empty(self):
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(id="story-002", status="in-progress"),
        )
        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
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
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002"],
        )

    def test_transitive_active_dependents_returned_sorted(self):
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
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
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
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            [],
        )

    def test_reviewing_dependent_cascades(self):
        # A reviewing dependent is mid-acceptance — if its base story has
        # to be deferred, the reviewing story's verification work is
        # invalidated and it must cascade-defer too. Without this widening,
        # /xp-accept would happily mark the reviewing story done against a
        # broken base.
        import sprint_store

        self._write(
            _make_story(id="story-001", status="in-progress"),
            _make_story(
                id="story-002",
                status="reviewing",
                dependencies=["story-001"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002"],
        )

    def test_closing_dependent_cascades(self):
        # AC #4: story-A 'in-progress' depending on story-B 'closing';
        # transitive_active_dependents(B) returns A. Proves
        # IN_MOTION_STORY_STATUSES auto-extension covers cascade-defer
        # for the new state — A is in-motion, so the walker treats it
        # as transitively blocked by B. (story-001 is the closing base
        # here so _write retains base-first ID-ascending convention
        # symmetric with test_reviewing_dependent_cascades.)
        import sprint_store

        self._write(
            _make_story(id="story-001", status="closing"),
            _make_story(
                id="story-002",
                status="in-progress",
                dependencies=["story-001"],
            ),
        )
        self.assertEqual(
            sprint_store.transitive_active_dependents(self.smm_dir, "story-001"),
            ["story-002"],
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
        result = sprint_store.transitive_active_dependents(self.smm_dir, "story-001")
        self.assertEqual(result, ["story-002"])


if __name__ == "__main__":
    unittest.main()
