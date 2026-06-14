#!/usr/bin/env python3
"""Tests for the ready-frontier query in sprint_store.py.

Covers ready_frontier{,_data}: dep-satisfied SCHEDULED stories the
/xp-schedule skill promotes. Split out of test_sprint_store.py for the
500-line cap — the frontier query is a distinct cohesive concern (the
CLI/preload-facing read path), separate from load/save and mutations.
The parallelizable verdict (ready_frontier_report) and CLI wiring are
tested in test_sprint_cli.py.
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


class TestReadyFrontier(_SMMTestCase):
    """ready_frontier{,_data}: dep-satisfied SCHEDULED stories, sorted.

    The frontier /xp-schedule promotes. Lifecycle is ready→scheduled
    (work-selection)→in-progress (/xp-schedule), so the frontier is over
    `scheduled`, NOT `ready`. A scheduled story is in the frontier iff all
    its deps are `done` (or in treat_as_done).
    """

    def _frontier(self, stories):
        import sprint_store

        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        return sprint_store.ready_frontier(self.smm_dir)

    def test_only_dep_free_scheduled_in_frontier(self):
        # 001 scheduled dep-free → in. 002 scheduled dep on 001 (not done)
        # → out. 003 ready → out (wrong status). 004 in-progress → out.
        stories = [
            _make_story(id="story-001", status="scheduled", dependencies=[]),
            _make_story(id="story-002", status="scheduled", dependencies=["story-001"]),
            _make_story(id="story-003", status="ready", dependencies=[]),
            _make_story(id="story-004", status="in-progress", dependencies=[]),
        ]
        self.assertEqual(self._frontier(stories), ["story-001"])

    def test_satisfied_deps_admit_to_frontier(self):
        stories = [
            _make_story(id="story-001", status="done", dependencies=[]),
            _make_story(id="story-002", status="scheduled", dependencies=["story-001"]),
        ]
        self.assertEqual(self._frontier(stories), ["story-002"])

    def test_multiple_dep_free_scheduled_sorted_numerically(self):
        stories = [
            _make_story(id="story-010", status="scheduled", dependencies=[]),
            _make_story(id="story-002", status="scheduled", dependencies=[]),
        ]
        self.assertEqual(self._frontier(stories), ["story-002", "story-010"])

    def test_empty_when_no_scheduled(self):
        stories = [_make_story(id="story-001", status="done", dependencies=[])]
        self.assertEqual(self._frontier(stories), [])

    def test_treat_as_done_unblocks_frontier(self):
        import sprint_store

        stories = [
            _make_story(id="story-001", status="closing", dependencies=[]),
            _make_story(id="story-002", status="scheduled", dependencies=["story-001"]),
        ]
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # 001 is closing (not done) so 002 is blocked; treat_as_done lifts it.
        self.assertEqual(sprint_store.ready_frontier(self.smm_dir), [])
        self.assertEqual(
            sprint_store.ready_frontier(self.smm_dir, treat_as_done={"story-001"}),
            ["story-002"],
        )

    def test_ready_frontier_data_is_pure(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled", dependencies=[]),
                _make_story(id="story-002", status="ready", dependencies=[]),
            ]
        )
        self.assertEqual(sprint_store.ready_frontier_data(sprint), ["story-001"])

    def test_ready_frontier_none_sprint_is_empty(self):
        import sprint_store

        self.assertEqual(sprint_store.ready_frontier(self.smm_dir), [])


if __name__ == "__main__":
    unittest.main()
