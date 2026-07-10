#!/usr/bin/env python3
"""Tests for sprint_status.py and the sprint_store re-export shim.

Pins the refactor-extraction-discipline contract (constraint 2c19173dad39):
sprint_status.py owns the 8 status-check functions; sprint_store.py
re-exports them so 16+ existing import sites keep working without churn.

Behavior tests for status / velocity / blocker / count helpers live here too
(split from test_sprint_store.py for the 500-line cap). The behavior tests
import via `sprint_store` to exercise the shim — the architectural test above
pins that the shim re-exports the same callables.
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


class TestSprintStatusModuleAndShim(unittest.TestCase):
    _STATUS_NAMES = (
        "has_active_stories",
        "has_active_stories_data",
        "has_stories_with_status",
        "has_stories_with_status_data",
        "has_in_progress_stories",
        "has_in_progress_stories_data",
        "has_reviewing_stories",
        "has_reviewing_stories_data",
        "has_closing_stories",
        "has_closing_stories_data",
        "has_under_acceptance_stories",
        "has_under_acceptance_stories_data",
        "has_in_motion_stories",
        "has_in_motion_stories_data",
        "select_in_motion_stories",
        "select_closing_stories",
        "has_ready_stories",
        "has_scheduled_stories",
        "schedule_gate_active",
        "schedule_gate_active_data",
        "is_complete",
    )

    def test_new_module_exposes_all_status_functions(self):
        import sprint_status

        for name in self._STATUS_NAMES:
            self.assertTrue(
                callable(getattr(sprint_status, name, None)),
                f"sprint_status.{name} should be a callable",
            )

    def test_sprint_store_reexports_status_functions(self):
        import sprint_status
        import sprint_store

        for name in self._STATUS_NAMES:
            store_fn = getattr(sprint_store, name, None)
            status_fn = getattr(sprint_status, name, None)
            self.assertIs(
                store_fn,
                status_fn,
                f"sprint_store.{name} must re-export sprint_status.{name}",
            )


class TestSprintStoreNativeHelperShim(unittest.TestCase):
    """Import guard for the sprint_store-native helpers not covered by the
    sprint_status `is`-identity check above.
    """

    def test_native_helpers_importable_from_sprint_store(self):
        from sprint_store import (  # noqa: F401
            compute_blockers,
            compute_velocity,
            count_by_status,
            next_scheduled_story_id,
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

    def test_has_reviewing_true_when_reviewing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="reviewing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_reviewing_stories(self.smm_dir))

    def test_has_reviewing_false_when_only_in_progress(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.has_reviewing_stories(self.smm_dir))

    def test_has_reviewing_false_when_missing_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.has_reviewing_stories(self.smm_dir))

    def test_has_closing_true_when_closing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="closing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_closing_stories(self.smm_dir))

    def test_has_closing_false_when_only_reviewing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="reviewing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.has_closing_stories(self.smm_dir))

    def test_has_closing_false_when_missing_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.has_closing_stories(self.smm_dir))

    def test_has_closing_data_true_and_false(self):
        import sprint_store

        sprint_yes = _make_sprint(stories=[_make_story(status="closing")])
        sprint_no = _make_sprint(stories=[_make_story(status="reviewing")])
        self.assertTrue(sprint_store.has_closing_stories_data(sprint_yes))
        self.assertFalse(sprint_store.has_closing_stories_data(sprint_no))

    def test_select_closing_stories(self):
        import sprint_store

        s_closing = _make_story(id="s1", status="closing")
        s_reviewing = _make_story(id="s2", status="reviewing")
        s_done = _make_story(id="s3", status="done")
        result = sprint_store.select_closing_stories([s_closing, s_reviewing, s_done])
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_has_in_motion_true_when_closing_only(self):
        # Regression guard on story-001's IN_MOTION extension: a sprint
        # with only a closing story still reports in-motion=True.
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="closing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_in_motion_true_when_in_progress(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_in_motion_true_when_reviewing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="reviewing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_in_motion_true_when_mixed(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="reviewing"),
                _make_story(id="s3", status="scheduled"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_in_motion_false_when_all_terminal_or_queued(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="deferred"),
                _make_story(id="s3", status="scheduled"),
                _make_story(id="s4", status="ready"),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertFalse(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_in_motion_false_when_missing_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.has_in_motion_stories(self.smm_dir))

    def test_has_under_acceptance_data_true_for_reviewing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="reviewing")])
        self.assertTrue(sprint_store.has_under_acceptance_stories_data(sprint))

    def test_has_under_acceptance_data_true_for_closing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="closing")])
        self.assertTrue(sprint_store.has_under_acceptance_stories_data(sprint))

    def test_has_under_acceptance_data_false_for_in_progress_only(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        self.assertFalse(sprint_store.has_under_acceptance_stories_data(sprint))

    def test_has_under_acceptance_data_false_for_terminal_only(self):
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="s1", status="done"),
                _make_story(id="s2", status="deferred"),
            ]
        )
        self.assertFalse(sprint_store.has_under_acceptance_stories_data(sprint))

    def test_has_under_acceptance_disk_true_when_closing(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="closing")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.has_under_acceptance_stories(self.smm_dir))

    def test_has_under_acceptance_disk_false_when_missing_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.has_under_acceptance_stories(self.smm_dir))

    def test_has_in_progress_data_true_and_false(self):
        import sprint_store

        sprint_yes = _make_sprint(stories=[_make_story(status="in-progress")])
        sprint_no = _make_sprint(stories=[_make_story(status="reviewing")])
        self.assertTrue(sprint_store.has_in_progress_stories_data(sprint_yes))
        self.assertFalse(sprint_store.has_in_progress_stories_data(sprint_no))

    def test_has_reviewing_data_true_and_false(self):
        import sprint_store

        sprint_yes = _make_sprint(stories=[_make_story(status="reviewing")])
        sprint_no = _make_sprint(stories=[_make_story(status="in-progress")])
        self.assertTrue(sprint_store.has_reviewing_stories_data(sprint_yes))
        self.assertFalse(sprint_store.has_reviewing_stories_data(sprint_no))

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
        nxt = sprint_store.next_scheduled_story_id(self.smm_dir)
        self.assertEqual(nxt, "story-002")

    def test_next_scheduled_none_when_no_scheduled(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="in-progress")])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertIsNone(sprint_store.next_scheduled_story_id(self.smm_dir))

    def test_next_scheduled_treats_as_done_satisfies_dep(self):
        # JIT-next race fix: /xp-story-close Step 8 runs BEFORE
        # /xp-accept Step 4 marks the just-closed story `done`. With
        # the dep gate requiring `done`, the next story would never
        # be promoted in solo mode when it depends on the just-closed
        # one. treat_as_done lets the caller assert "this id is about
        # to be done" so the dep check passes.
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", status="closing"),
                _make_story(
                    id="story-002", status="scheduled", dependencies=["story-001"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Without the override: dep is `closing` not `done`, so None.
        self.assertIsNone(sprint_store.next_scheduled_story_id(self.smm_dir))
        # With the override: dep treated as satisfied; story-002 surfaces.
        self.assertEqual(
            sprint_store.next_scheduled_story_id(
                self.smm_dir, treat_as_done={"story-001"}
            ),
            "story-002",
        )

    def test_next_scheduled_treat_as_done_does_not_promote_in_progress(self):
        # Override only satisfies deps; it MUST NOT make a story whose
        # own status is `in-progress` appear in the scheduled-set query.
        # Setup: only an in-progress story exists, no scheduled. With or
        # without the override naming the in-progress id, the
        # next-scheduled query must return None.
        import sprint_store

        sprint = _make_sprint(
            stories=[_make_story(id="story-001", status="in-progress")]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        # Override naming story-001 must NOT surface it as next-scheduled —
        # treat_as_done relaxes deps, not the status filter.
        self.assertIsNone(
            sprint_store.next_scheduled_story_id(
                self.smm_dir, treat_as_done={"story-001"}
            )
        )

    def test_scheduled_file_domains_overlap_is_removed(self):
        # Deleted: solo vs parallel verdict moved to /xp-schedule's
        # parallelizable flag. Guards against reintroduction.
        import sprint_status
        import sprint_store

        self.assertFalse(hasattr(sprint_status, "scheduled_file_domains_overlap"))
        self.assertNotIn("scheduled_file_domains_overlap", sprint_store.__all__)

    def test_sprint_exists(self):
        import sprint_store

        self.assertFalse(sprint_store.sprint_exists(self.smm_dir))
        (self.smm_dir / "sprint.json").write_text(json.dumps(_make_sprint()))
        self.assertTrue(sprint_store.sprint_exists(self.smm_dir))


# ===========================================================================
# Computed fields
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
