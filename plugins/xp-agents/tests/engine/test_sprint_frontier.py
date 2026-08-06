#!/usr/bin/env python3
"""Tests for the ready-frontier query in sprint_store.py.

Covers ready_frontier{,_data}: dep-satisfied SCHEDULED stories the
/xp-schedule skill promotes. Split out of test_sprint_store.py for the
500-line cap — the frontier query is a distinct cohesive concern (the
CLI/preload-facing read path), separate from load/save and mutations.
The parallelizable verdict (ready_frontier_report) and CLI wiring are
tested in test_sprint_cli.py. The unscoped verdict lives in
test_frontier_unprovable.py, and the dependency-edge / treat_as_done
interaction lives in test_frontier_dependency_edges.py — both split out
once this file neared its own line ceiling.
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


class TestSprintFrontierModuleAndShim(unittest.TestCase):
    """Pins the extraction: bodies live in sprint_frontier.py, sprint_store
    re-exports the same callables (not copies) so both old and new import
    paths keep working.
    """

    _FRONTIER_NAMES = (
        "ready_frontier",
        "ready_frontier_data",
        "ready_frontier_report",
        "transitive_active_dependents",
        "next_in_progress_story_id",
        "next_scheduled_story_id",
    )

    def test_new_module_exposes_all_frontier_functions(self):
        import sprint_frontier

        for name in self._FRONTIER_NAMES:
            self.assertTrue(
                hasattr(sprint_frontier, name), f"sprint_frontier missing {name}"
            )

    def test_sprint_store_reexports_are_identical_objects(self):
        import sprint_frontier
        import sprint_store

        for name in self._FRONTIER_NAMES:
            self.assertIs(
                getattr(sprint_store, name),
                getattr(sprint_frontier, name),
                f"{name} was copied, not moved",
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


class TestReadyFrontierReport(_SMMTestCase):
    """ready_frontier_report: frontier + parallelizable verdict + overlap
    detail, in one load. The overlap dict is story-002's
    file_domains_overlap_detail forwarded verbatim — collisions and
    glob_forced are distinct signals, never folded together.
    """

    def _report(self, stories, *, treat_as_done=None):
        import sprint_store

        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        return sprint_store.ready_frontier_report(
            self.smm_dir, treat_as_done=treat_as_done
        )

    def test_report_names_shared_path_and_owners(self):
        report = self._report(
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
        self.assertFalse(report["parallelizable"])
        self.assertEqual(list(report["overlap"]["collisions"]), ["shared.py"])
        self.assertEqual(
            [c["story_id"] for c in report["overlap"]["collisions"]["shared.py"]],
            ["story-001", "story-002"],
        )

    def test_report_disjoint_frontier_is_parallelizable(self):
        report = self._report(
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
        self.assertTrue(report["parallelizable"])
        self.assertEqual(
            report["overlap"],
            {"collisions": {}, "glob_forced": False, "unscoped": []},
        )

    def test_report_glob_frontier_not_parallelizable(self):
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["src/*"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["docs/api.md"],
                ),
            ]
        )
        self.assertFalse(report["parallelizable"])
        self.assertTrue(report["overlap"]["glob_forced"])
        self.assertEqual(report["overlap"]["collisions"], {})

    def test_report_single_story_frontier_has_empty_overlap(self):
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py"],
                ),
            ]
        )
        self.assertFalse(report["parallelizable"])
        self.assertEqual(
            report["overlap"],
            {"collisions": {}, "glob_forced": False, "unscoped": []},
        )

    def test_report_no_sprint_has_consistent_shape(self):
        import sprint_store

        report = sprint_store.ready_frontier_report(self.smm_dir)
        self.assertEqual(
            report,
            {
                "frontier": [],
                "parallelizable": False,
                "overlap": {"collisions": {}, "glob_forced": False, "unscoped": []},
            },
        )

    def test_report_preserves_frontier_and_parallelizable_keys(self):
        report = self._report(
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
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertTrue(report["parallelizable"])


if __name__ == "__main__":
    unittest.main()
