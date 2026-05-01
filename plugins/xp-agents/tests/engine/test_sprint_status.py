#!/usr/bin/env python3
"""Tests for sprint_store.py status / velocity / blocker / count helpers.

Split from test_sprint_store.py (over the 500-line cap). Same import
surface — `sprint_store` exposes all of these at module scope, so the
shim-import test is a fast guard against accidental renames.
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


class TestSprintStoreStatusShim(unittest.TestCase):
    """One-line shim-import guard against renames in sprint_store."""

    def test_status_helpers_importable_from_sprint_store(self):
        from sprint_store import (  # noqa: F401
            compute_blockers,
            compute_velocity,
            count_by_status,
            has_active_stories,
            has_in_progress_stories,
            has_ready_stories,
            has_scheduled_stories,
            is_complete,
            next_scheduled_story_id,
            scheduled_file_domains_overlap,
            sprint_exists,
        )


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

    def test_has_scheduled(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="scheduled")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_scheduled_stories(self.smm_dir))

    def test_has_scheduled_false_when_only_in_progress(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.has_scheduled_stories(self.smm_dir))

    def test_next_scheduled_returns_lowest_id_with_deps_done(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="done"),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
                _make_story(
                    id="story-003", status="scheduled", dependencies=["story-002"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # story-002 is scheduled and its dep (story-001) is done; story-003's
        # dep (story-002) is scheduled, not done, so story-003 is blocked.
        nxt = sprint_store.next_scheduled_story_id(self.smm_dir)
        self.assertEqual(nxt, "story-002")

    def test_next_scheduled_none_when_no_scheduled(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertIsNone(sprint_store.next_scheduled_story_id(self.smm_dir))

    def test_scheduled_file_domains_overlap_true_when_shared_file(self):
        import sprint_store

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
        # Path portion (before " — ") is what counts; descriptions vary.
        self.assertTrue(sprint_store.scheduled_file_domains_overlap(self.smm_dir))

    def test_scheduled_file_domains_overlap_false_when_disjoint(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/a.py"]
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.scheduled_file_domains_overlap(self.smm_dir))

    def test_scheduled_file_domains_overlap_false_when_single_scheduled(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled", file_domain=["a.py"]),
                _make_story(id="story-002", status="ready", file_domain=["a.py"]),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Only one scheduled story — no pair to overlap. Not a conflict.
        self.assertFalse(sprint_store.scheduled_file_domains_overlap(self.smm_dir))

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
                _make_story(id="s5", status="scheduled"),
            ]
        )
        counts = sprint_store.count_by_status(sprint)
        self.assertEqual(counts["ready"], 1)
        self.assertEqual(counts["scheduled"], 1)
        self.assertEqual(counts["in-progress"], 1)
        self.assertEqual(counts["done"], 1)
        self.assertEqual(counts["deferred"], 1)


if __name__ == "__main__":
    unittest.main()
