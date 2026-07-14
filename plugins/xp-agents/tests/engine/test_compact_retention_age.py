#!/usr/bin/env python3
"""Commit retention is bounded by AGE, not only by the retro marker.

`_collect_smm_referenced_ids` pins every commit whose sprint is "pending retro",
and the release condition is a `sprint_retro_done` status event. No such event
was ever written — `save_retrospective` emitted that action string on a
RETROSPECTIVE-type event with no `sprint_id`, and both readers require a STATUS
type AND a sprint_id, so it missed on two counts (debt ef03cbc32f1e). A sprint
therefore never left `pending_retro_sprint_ids`, and the rule was in practice
"retain every commit forever".

Measured across all 11 projects the plugin ships to, `retro_done = 0` in EVERY
one: 857/1161 events pinned in the worst, 517 commits = 61% of this project's own
1.1 MB log — re-read and re-parsed by every hook invocation.

**The age rule is what heals those logs, and it must NOT depend on the marker.**
Backfilling a marker would need a manual migration in each project; a rule inside
compaction repairs them on the next SessionEnd. So the load-bearing test here is
`TestSelfHealingWithoutAnyMarker`: a log with ZERO `sprint_retro_done` events —
today's real state everywhere — must still release its historical commits. If
that needs the marker, the fix does not heal existing projects and is wrong.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import compact
import compact_retention
import materialize
from conftest import _SMMTestCase, commit_event, make_event
from event_schema import (
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
    SPRINT_ACTION_START,
)


class _SprintRetentionTestCase(_SMMTestCase):
    def _sprint_start(self, sprint_id: str, day: int) -> dict:
        return make_event(
            EVENT_TYPE_SPRINT,
            content=f"Start {sprint_id}",
            ts=f"2026-01-{day:02d}T00:00:00+00:00",
            metadata={"sprint_id": sprint_id, "action": SPRINT_ACTION_START},
        )

    def _commit(self, sprint_id: str, day: int) -> dict:
        return commit_event(
            files=["src/foo.py"],
            ts=f"2026-01-{day:02d}T12:00:00+00:00",
            story_id="story-001",
            sprint_id=sprint_id,
        )

    def _compact(self, pre_watermark: list[dict]) -> list[dict]:
        trailing = make_event(
            EVENT_TYPE_STATUS, content="uncurated", ts="2026-06-01T00:00:00+00:00"
        )
        self._write_events([*pre_watermark, trailing])
        materialize.write_curation_watermark(
            self.smm_dir, len(pre_watermark), "xp-housekeeper"
        )
        compact.compact_after_curation(self.smm_dir)
        return self._read_events()

    def _archived_ids(self) -> set[str]:
        """Every id written to backups/ — released, never destroyed (AC6)."""
        import json

        ids: set[str] = set()
        for archive in (self.smm_dir / "backups").glob("archive-*.jsonl"):
            for line in archive.read_text().splitlines():
                if line.strip():
                    ids.add(json.loads(line)["id"])
        return ids


class TestSelfHealingWithoutAnyMarker(_SprintRetentionTestCase):
    """AC5 + AC7. The state of every real log today: no `sprint_retro_done`
    event has ever been written, so every sprint is pending-retro forever."""

    def _three_sprints_no_retro(self) -> tuple[list[dict], list[dict]]:
        events: list[dict] = []
        commits: list[dict] = []
        for i in (1, 2, 3):
            events.append(self._sprint_start(f"sprint-{i:03d}", i * 2))
            commit = self._commit(f"sprint-{i:03d}", i * 2)
            commits.append(commit)
            events.append(commit)
        events.append(
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start",
                ts="2026-02-01T00:00:00+00:00",
            )
        )
        return events, commits

    def test_no_retro_marker_exists_in_this_log(self):
        """Guard the guard. If a marker leaked into the fixture, every test in
        this class would pass through the OLD release path and prove nothing
        about self-healing."""
        events, _ = self._three_sprints_no_retro()
        self.assertEqual(
            [
                e
                for e in events
                if e.get("metadata", {}).get("action") == "sprint_retro_done"
            ],
            [],
        )

    def test_commits_older_than_the_last_two_sprints_are_released(self):
        events, commits = self._three_sprints_no_retro()

        live = self._compact(events)
        live_ids = {e["id"] for e in live}

        self.assertNotIn(
            commits[0]["id"],
            live_ids,
            "sprint-001 is three sprints back and its retro will never run — "
            "without an age rule its commits are pinned forever",
        )
        # The recent sprints keep theirs: a retro may still be coming, and the
        # sprint-retro path (story_metrics / retro_metrics) reads those commits
        # to compute per-story sizing.
        self.assertIn(commits[1]["id"], live_ids)
        self.assertIn(commits[2]["id"], live_ids)

    def test_released_commits_are_archived_not_destroyed(self):
        """AC6. Released means MOVED to backups/, and the live count drops —
        asserted on counts, not on the absence of an error."""
        events, commits = self._three_sprints_no_retro()
        before = len(events) + 1  # + the uncurated trailing event

        live = self._compact(events)

        self.assertLess(len(live), before, "the live log must actually shrink")
        self.assertIn(commits[0]["id"], self._archived_ids())

    def test_the_old_sprint_start_is_released_too(self):
        """The identical defect on the sprint/start arm: a start event was
        pinned for as long as its sprint was pending-retro, i.e. forever."""
        events, _ = self._three_sprints_no_retro()
        oldest_start = events[0]

        live = self._compact(events)

        self.assertNotIn(oldest_start["id"], {e["id"] for e in live})
        self.assertIn(oldest_start["id"], self._archived_ids())


class TestSprintsRankByFilePositionNotIdString(_SprintRetentionTestCase):
    """The id format is a CONVENTION, not a schema rule, and lexicographic order
    inverts at `sprint-1000` ("sprint-1000" < "sprint-999"). Ranking by string
    would silently pin the wrong sprints' commits the day a project's 1000th
    sprint starts — and release the CURRENT one's. Rules 1-5 of
    `_classify_pre_watermark` already rank by file position; so does this.
    """

    def test_recent_means_last_started_not_highest_id(self):
        events = [
            self._sprint_start("sprint-999", 2),
            self._commit("sprint-999", 2),
            self._sprint_start("sprint-1000", 4),
            self._commit("sprint-1000", 4),
            self._sprint_start("sprint-1001", 6),
            self._commit("sprint-1001", 6),
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content="start",
                ts="2026-02-01T00:00:00+00:00",
            ),
        ]
        # Lexicographically, "sprint-999" sorts ABOVE both four-digit ids, so a
        # string-ranked rule would call it one of the two most recent sprints and
        # pin its commits while releasing sprint-1000's.
        self.assertEqual(
            sorted(["sprint-999", "sprint-1000", "sprint-1001"])[-2:],
            ["sprint-1001", "sprint-999"],
            "guard the guard: if string order ever agrees with file order, this "
            "test has stopped discriminating between the two rules",
        )

        self.assertEqual(
            compact_retention._recent_sprint_ids(events),
            {"sprint-1000", "sprint-1001"},
        )

        live_ids = {e["id"] for e in self._compact(events)}
        self.assertNotIn(events[1]["id"], live_ids, "sprint-999's commit")
        self.assertIn(events[3]["id"], live_ids, "sprint-1000's commit")
        self.assertIn(events[5]["id"], live_ids, "sprint-1001's commit")


class TestMarkerStillReleasesPromptly(_SprintRetentionTestCase):
    """The age rule is the floor, not a replacement. A sprint whose retro HAS run
    releases its commits at the next compaction — it does not wait to age out."""

    def test_retro_done_releases_the_current_sprint(self):
        start = self._sprint_start("sprint-001", 2)
        commit = self._commit("sprint-001", 2)
        retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
        )
        anchor = make_event(
            EVENT_TYPE_SESSION_STARTED,
            content="start",
            ts="2026-02-01T00:00:00+00:00",
        )

        live_ids = {e["id"] for e in self._compact([start, commit, retro_done, anchor])}

        self.assertNotIn(
            commit["id"],
            live_ids,
            "sprint-001 is the MOST RECENT sprint, so only the marker can "
            "release it — the age rule alone would still be pinning it",
        )


if __name__ == "__main__":
    unittest.main()
