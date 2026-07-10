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
        "scheduled_file_domains_overlap",
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
        self.assertFalse(sprint_store.scheduled_file_domains_overlap(self.smm_dir))

    def test_scheduled_file_domains_overlap_true_when_glob_entry(self):
        # Conservative-overlap=True on glob: rc=1 from a crash was indistinguishable
        # from "no overlap" and silently masked the failure at xp-assign.
        import sprint_store

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-006",
                    status="scheduled",
                    file_domain=["packages/db/drizzle/meta/*"],
                ),
                _make_story(
                    id="story-007", status="scheduled", file_domain=["src/api.py"]
                ),
            ]
        )
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        self.assertTrue(sprint_store.scheduled_file_domains_overlap(self.smm_dir))

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

    def test_counts_includes_closing(self):
        # Regression guard on story-001's VALID_STORY_STATUSES extension:
        # count_by_status auto-derives keys from the frozenset, so adding
        # 'closing' there should make the closing key appear here without
        # any edit to count_by_status itself.
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(status="closing")])
        counts = sprint_store.count_by_status(sprint)
        self.assertEqual(counts.get("closing"), 1)


class TestFileDomainsOverlapDetail(unittest.TestCase):
    """file_domains_overlap_detail: the detail-returning sibling of the
    overlap bool, backed by file_domain_lock.collision_report so there is
    exactly one file_domain parser.

    `collisions` is collision_report's output forwarded unchanged (path ->
    owning claims with origin). `glob_forced` is a SEPARATE signal, not
    folded into collisions: collision_report compares glob tokens as literal
    strings and would report a glob-declared frontier as disjoint, so the
    detail helper re-detects globs with the same oracle the legacy bool used
    (extract_file_domain_paths raising ValueError) and reports the
    conservative "can't prove disjoint" verdict on its own field. Callers
    need to distinguish "these two stories both claim x.py" from "a glob
    domain means disjointness can't be proven".
    """

    def _detail(self, stories, story_ids):
        import sprint_status

        return sprint_status.file_domains_overlap_detail(
            {"stories": stories}, story_ids
        )

    def test_detail_reports_collision_path_and_story_ids(self):
        detail = self._detail(
            [
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
            ],
            ["story-001", "story-002"],
        )
        self.assertFalse(detail["glob_forced"])
        self.assertEqual(list(detail["collisions"]), ["src/b.py"])
        self.assertEqual(
            [c["story_id"] for c in detail["collisions"]["src/b.py"]],
            ["story-001", "story-002"],
        )

    def test_detail_disjoint_no_collisions(self):
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/a.py"]
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_empty_for_single_story(self):
        # Fewer than two named stories: no pair, so no claim about paths —
        # and the glob detector never runs (legacy "single glob story ->
        # False" behavior preserved).
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=["src/*"]),
                _make_story(id="story-002", status="ready", file_domain=["src/a.py"]),
            ],
            ["story-001"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_glob_forced_true(self):
        # collision_report compares "src/*" as a literal token and would say
        # disjoint. glob_forced carries the conservatism instead.
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=["src/*"]),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["docs/api.md"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertTrue(detail["glob_forced"])
        self.assertEqual(detail["collisions"], {})

    def test_detail_glob_in_non_subset_story_ignored(self):
        # The question is only about the named stories. A glob elsewhere in
        # the sprint must not force conservatism on this frontier.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/a.py"]
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(id="story-003", status="ready", file_domain=["src/*"]),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_origin_auto_included_preserved(self):
        # The sister-test globber's claims are tagged auto_included, and the
        # tag survives forwarding — the remedy differs from an authored clash.
        detail = self._detail(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["tests/test_a.py — sister test for src/a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["tests/test_a.py — authored"],
                ),
            ],
            ["story-001", "story-002"],
        )
        claims = detail["collisions"]["tests/test_a.py"]
        self.assertEqual(
            {c["story_id"]: c["origin"] for c in claims},
            {"story-001": "auto_included", "story-002": "authored"},
        )

    def test_detail_dependency_serialized_not_collision(self):
        # Sequential work sharing a file is legal — the dependency edge means
        # the two stories can never run concurrently.
        detail = self._detail(
            [
                _make_story(
                    id="story-001", status="scheduled", file_domain=["src/b.py"]
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    file_domain=["src/b.py"],
                    dependencies=["story-001"],
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_terminal_story_not_collision(self):
        # A done story has merged and released its files.
        detail = self._detail(
            [
                _make_story(id="story-001", status="done", file_domain=["src/b.py"]),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_non_str_entries_ignored(self):
        # entry_to_paths raises TypeError (not ValueError) on a non-str entry,
        # a latent crash in the legacy bool. Filter before the detector runs.
        detail = self._detail(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    file_domain=["src/b.py", 42, None],
                ),
                _make_story(
                    id="story-002", status="scheduled", file_domain=["src/b.py"]
                ),
            ],
            ["story-001", "story-002"],
        )
        self.assertFalse(detail["glob_forced"])
        self.assertEqual(list(detail["collisions"]), ["src/b.py"])

    def test_detail_empty_file_domain_makes_no_claims(self):
        # Code-free investigation stories declare nothing: no raise, no claim.
        detail = self._detail(
            [
                _make_story(id="story-001", status="scheduled", file_domain=[]),
                _make_story(id="story-002", status="scheduled", file_domain=[]),
            ],
            ["story-001", "story-002"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_unknown_story_id_is_not_a_pair(self):
        detail = self._detail(
            [_make_story(id="story-001", status="scheduled", file_domain=["src/a.py"])],
            ["story-001", "story-404"],
        )
        self.assertEqual(detail, {"collisions": {}, "glob_forced": False})

    def test_detail_called_as_sprint_frontier_will_call_it(self):
        # AC#5: sprint_frontier imports these helpers DIRECTLY from
        # sprint_status, never through sprint_store's re-export shim (there is
        # no re-export of the detail helper, by design). Exercise that path.
        from sprint_status import file_domains_overlap_detail

        sprint = _make_sprint(
            stories=[
                _make_story(
                    id="story-001",
                    status="in-progress",
                    file_domain=["smm/sprint_status.py — owner"],
                ),
                _make_story(
                    id="story-002",
                    status="in-progress",
                    file_domain=["smm/sprint_status.py — consumer"],
                ),
            ]
        )
        detail = file_domains_overlap_detail(sprint, ["story-001", "story-002"])
        self.assertEqual(
            detail["collisions"],
            {
                "smm/sprint_status.py": [
                    {"story_id": "story-001", "origin": "authored"},
                    {"story_id": "story-002", "origin": "authored"},
                ]
            },
        )


class TestScheduleGateActive(_SMMTestCase):
    """schedule_gate_active{,_data}: the trigger the /xp-schedule gates fire
    on — scheduled stories exist AND no story is in motion (in-progress,
    reviewing, or closing). That is exactly the "work-selection scheduled
    work, no frontier promoted yet" window; /xp-schedule is the sole
    legitimate exit (promotes scheduled->in-progress). The in-motion guard
    keeps the gate quiet during the /xp-story-close window so review-cycle
    fixes to the closing story aren't blocked by a demand to promote the
    still-scheduled next frontier.
    """

    def _write(self, stories):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_active_when_scheduled_and_none_in_progress(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="scheduled")])
        self.assertTrue(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_any_in_progress(self):
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="in-progress"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_story_closing(self):
        """The /xp-story-close window: one story closing, next still
        scheduled. The gate must stay quiet so review-cycle fixes to the
        closing story aren't blocked by a /xp-schedule demand that would
        wrongly promote the next frontier mid-close.
        """
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="closing"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_story_reviewing(self):
        """The /xp-accept review window: one story reviewing, next still
        scheduled. Same as closing — fix-cycle writes belong to the
        reviewing story, not the next frontier.
        """
        import sprint_store

        self._write(
            [
                _make_story(id="story-001", status="reviewing"),
                _make_story(id="story-002", status="scheduled"),
            ]
        )
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_no_scheduled(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="in-progress")])
        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_inactive_when_no_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.schedule_gate_active(self.smm_dir))

    def test_data_twin_is_pure(self):
        import sprint_status

        active = _make_sprint(stories=[_make_story(status="scheduled")])
        blocked = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled"),
                _make_story(id="story-002", status="in-progress"),
            ]
        )
        closing = _make_sprint(
            stories=[
                _make_story(id="story-001", status="scheduled"),
                _make_story(id="story-002", status="closing"),
            ]
        )
        self.assertTrue(sprint_status.schedule_gate_active_data(active))
        self.assertFalse(sprint_status.schedule_gate_active_data(blocked))
        self.assertFalse(sprint_status.schedule_gate_active_data(closing))


class TestInProgressIsTeammate(_SMMTestCase):
    """in_progress_is_teammate{,_data}: True iff any in-progress story is
    execution_mode=='teammate'. The signal subagent_stop's plan-review gate
    keys on — only teammate-mode plans need /xp-assign, so solo/unset plan
    reviews must leave no .assign-pending marker. Conservative default False.
    """

    def _write(self, stories):
        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))

    def test_true_when_in_progress_teammate(self):
        import sprint_store

        self._write(
            [
                _make_story(
                    id="story-001", status="in-progress", execution_mode="teammate"
                )
            ]
        )
        self.assertTrue(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_in_progress_solo(self):
        import sprint_store

        self._write(
            [_make_story(id="story-001", status="in-progress", execution_mode="solo")]
        )
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_execution_mode_unset(self):
        import sprint_store

        self._write([_make_story(id="story-001", status="in-progress")])
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_teammate_but_not_in_progress(self):
        import sprint_store

        # A teammate-mode story still in reviewing is not the just-planned unit.
        self._write(
            [_make_story(id="story-001", status="reviewing", execution_mode="teammate")]
        )
        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_false_when_no_sprint(self):
        import sprint_store

        self.assertFalse(sprint_store.in_progress_is_teammate(self.smm_dir))

    def test_data_twin_is_pure(self):
        import sprint_status

        teammate = _make_sprint(
            stories=[_make_story(status="in-progress", execution_mode="teammate")]
        )
        solo = _make_sprint(
            stories=[_make_story(status="in-progress", execution_mode="solo")]
        )
        self.assertTrue(sprint_status.in_progress_is_teammate_data(teammate))
        self.assertFalse(sprint_status.in_progress_is_teammate_data(solo))


if __name__ == "__main__":
    unittest.main()
