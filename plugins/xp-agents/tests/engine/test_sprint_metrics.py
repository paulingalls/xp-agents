#!/usr/bin/env python3
"""Tests for sprint_metrics.py and the sprint_store re-export shim.

Pins the refactor-extraction-discipline contract (decision 03cb90c9b2d7):
sprint_metrics.py owns the computed-field helpers (count_by_status,
compute_velocity, compute_blockers, list_stories, next_sprint_id);
sprint_store.py re-exports them so existing import sites keep working
without churn. Behavior tests for these functions already live in
test_sprint_status.py and test_sprint_cli.py — the identity check here
only pins that the bodies were MOVED, not copied.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
    make_event,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)
from event_schema import EVENT_TYPE_SPRINT


class TestSprintMetricsModuleAndShim(unittest.TestCase):
    """Pins the extraction: bodies live in sprint_metrics.py, sprint_store
    re-exports the same callables (not copies) so both old and new import
    paths keep working.
    """

    _METRICS_NAMES = (
        "count_by_status",
        "compute_velocity",
        "compute_blockers",
        "list_stories",
        "next_sprint_id",
    )

    def test_new_module_exposes_all_metrics_functions(self):
        import sprint_metrics

        for name in self._METRICS_NAMES:
            self.assertTrue(
                hasattr(sprint_metrics, name), f"sprint_metrics missing {name}"
            )

    def test_sprint_store_reexports_are_identical_objects(self):
        import sprint_metrics
        import sprint_store

        for name in self._METRICS_NAMES:
            self.assertIs(
                getattr(sprint_store, name),
                getattr(sprint_metrics, name),
                f"{name} was copied, not moved",
            )


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


class TestNextSprintId(_SMMTestCase):
    """next_sprint_id must return MAX EXISTING id + 1 across live sprint,
    archived sprints/*.json, and sprint-start events — never a count.
    """

    def _write_archive(self, sprint_id: str, name: str = "sprint_20260101T000000.json"):
        sprints_dir = self.smm_dir / "sprints"
        sprints_dir.mkdir(exist_ok=True)
        (sprints_dir / name).write_text(
            json.dumps({"sprint_id": sprint_id}), encoding="utf-8"
        )

    def _write_live_sprint(self, sprint_id: str):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(sprint_id=sprint_id)), encoding="utf-8"
        )

    def _seed_sprint_start_event(self, sprint_id: str):
        e = make_event(
            EVENT_TYPE_SPRINT,
            content=f"start {sprint_id}",
            metadata={"action": "start", "sprint_id": sprint_id},
        )
        with (self.smm_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(e) + "\n")

    def test_archived_only_returns_next_after_max_archive_not_a_count(self):
        import sprint_store

        self._write_archive("sprint-120")
        result = sprint_store.next_sprint_id(self.smm_dir)
        self.assertEqual(result, "sprint-121")

    def test_result_collides_with_no_source(self):
        import sprint_store

        self._write_live_sprint("sprint-050")
        self._write_archive("sprint-075")
        self._seed_sprint_start_event("sprint-030")
        result = sprint_store.next_sprint_id(self.smm_dir)
        self.assertEqual(result, "sprint-076")

    def test_no_history_anywhere_returns_sprint_001(self):
        import sprint_store

        result = sprint_store.next_sprint_id(self.smm_dir)
        self.assertEqual(result, "sprint-001")

    def test_e2e_real_repo_smm_dir_id_exceeds_all_archived_ids(self):
        import sprint_store

        real_smm_dir = Path(
            "/Users/paulingalls/.claude/plugins/data/xp-agents-xp-agents/8e1f07eb0759/smm"
        )
        sprints_dir = real_smm_dir / "sprints"
        if not sprints_dir.is_dir():
            self.skipTest("real repo SMM dir not present in this environment")

        max_archived = 0
        for path in sprints_dir.glob("*.json"):
            try:
                sid = json.loads(path.read_text(encoding="utf-8")).get("sprint_id", "")
            except (OSError, json.JSONDecodeError):
                continue
            parts = sid.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                max_archived = max(max_archived, int(parts[1]))

        result = sprint_store.next_sprint_id(real_smm_dir)
        parts = result.rsplit("-", 1)
        self.assertEqual(parts[0], "sprint")
        self.assertGreater(int(parts[1]), max_archived)


if __name__ == "__main__":
    unittest.main()
