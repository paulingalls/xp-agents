#!/usr/bin/env python3
"""Tests for curation-watermark compaction: sprint lifecycle and team watermarks.

Split from test_compact_curation.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import materialize
from conftest import _SMMTestCase, commit_event, make_event
from event_schema import (
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_SESSION_END,
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
)


class TestCompactCurationTeamAndSprint(_SMMTestCase):
    """Tests for team watermark handling and sprint event compaction."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        ts_base = f"2026-03-{session_num:02d}T00:00:00+00:00"
        events = [
            make_event(
                EVENT_TYPE_CUSTOMER_INPUT,
                content=f"session {session_num} event {i}",
                ts=ts_base,
            )
            for i in range(event_count)
        ]
        events.append(
            make_event(
                EVENT_TYPE_SESSION_END,
                content=f"end session {session_num}",
                ts=ts_base,
                working_on=[],
            )
        )
        return events

    def _set_curation_watermark(
        self, event_count: int, agent_id: str = "xp-housekeeper"
    ):
        materialize.write_curation_watermark(self.smm_dir, event_count, agent_id)

    def test_team_safety_uses_oldest_watermark(self):
        """With multiple curation watermarks, uses min(event_count)."""
        import compact

        all_events = []
        for i in range(1, 4):
            all_events.extend(self._make_session(session_num=i))
        filler = make_event(
            EVENT_TYPE_STATUS, content="filler", ts="2026-04-01T00:00:00+00:00"
        )
        all_events.append(filler)
        self._write_events(all_events)

        self._set_curation_watermark(8, agent_id="agent-a")
        self._set_curation_watermark(4, agent_id="agent-b")

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        self.assertGreaterEqual(len(retained), len(all_events) - 4)

    def test_retains_active_sprint_start(self):
        """Sprint start with no matching end is retained (active sprint)."""
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "start",
                # intentional literal: sprint metadata key, not an event type
                "goal": "Build user API",
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_start, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_start["id"], retained_ids)

    def test_archives_sprint_start_after_retro_done(self):
        """Sprint start is archived once sprint_retro_done has fired.

        Sprint start must remain retained while a sprint is started but
        not yet retro'd, so _compute_pending_retro_sprint_ids can keep
        attributing commits to it across multiple compactions.
        """
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={"sprint_id": "sprint-001", "action": "start"},
        )
        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events(
            [sprint_start, sprint_end, retro_done, session_end, new_event]
        )
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(sprint_start["id"], retained_ids)

    def test_retains_latest_sprint_end(self):
        """Most recent sprint end retained for velocity data."""
        import compact

        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_end, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_end["id"], retained_ids)

    def test_archives_old_sprint_ends(self):
        """Only the most recent sprint end is retained."""
        import compact

        sprint_end_1 = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint 1 complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        sprint_end_2 = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint 2 complete",
            ts="2026-01-15T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-002",
                "action": "end",
                "stories_planned": 8,
                "stories_delivered": 7,
                "stories_carried": 1,
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-16T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_end_1, sprint_end_2, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_end_2["id"], retained_ids)
        self.assertNotIn(sprint_end_1["id"], retained_ids)

    def test_retains_sprint_retro_done_paired_with_sprint_end(self):
        """sprint_retro_done paired with retained sprint_end is kept."""
        import compact

        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        sprint_retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_end, sprint_retro_done, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_end["id"], retained_ids)
        self.assertIn(sprint_retro_done["id"], retained_ids)

    def test_archives_stale_sprint_retro_done(self):
        """sprint_retro_done without matching retained sprint_end is archived."""
        import compact

        sprint_end_old = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint 1 complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        retro_done_old = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        sprint_end_new = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint 2 complete",
            ts="2026-01-15T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-002",
                "action": "end",
                "stories_planned": 8,
                "stories_delivered": 7,
                "stories_carried": 1,
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-16T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events(
            [
                sprint_end_old,
                retro_done_old,
                sprint_end_new,
                session_end,
                new_event,
            ]
        )
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_end_new["id"], retained_ids)
        self.assertNotIn(sprint_end_old["id"], retained_ids)
        self.assertNotIn(retro_done_old["id"], retained_ids)

    def test_detection_works_after_compaction(self):
        """Round-trip: seed, compact, run needs_sprint_retro -> None."""
        import compact
        import retrospective

        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 5,
                "stories_delivered": 4,
                "stories_carried": 1,
            },
        )
        retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_end, retro_done, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        self.assertIsNone(retrospective.needs_sprint_retro(retained))

    def test_watermark_updated_true_when_compaction_runs(self):
        """Return includes watermark_updated=True when main path runs."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        self._set_curation_watermark(len(events))

        result = compact.compact_after_curation(self.smm_dir)
        self.assertTrue(result["watermark_updated"])

    def test_watermark_updated_false_no_events_file(self):
        """Return includes watermark_updated=False when no events file."""
        import compact

        result = compact.compact_after_curation(self.smm_dir)
        self.assertFalse(result["watermark_updated"])

    def test_watermark_updated_false_no_watermarks(self):
        """Return includes watermark_updated=False when no watermarks."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)

        result = compact.compact_after_curation(self.smm_dir)
        self.assertFalse(result["watermark_updated"])

    def test_commit_retained_for_active_sprint(self):
        """Commit with sprint_id of active sprint (no end yet) is retained."""
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "start",
                # intentional literal: sprint metadata key, not an event type
                "goal": "Build user API",
            },
        )
        commit = commit_event(
            files=["src/foo.py"],
            ts="2026-01-02T00:00:00+00:00",
            story_id="story-001",
            sprint_id="sprint-001",
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_start, commit, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(commit["id"], retained_ids)

    def test_commit_retained_for_ended_sprint_pending_retro(self):
        """Commit retained when sprint ended but retro_done not yet recorded."""
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={"sprint_id": "sprint-001", "action": "start"},
        )
        commit = commit_event(
            files=["src/foo.py"],
            ts="2026-01-02T00:00:00+00:00",
            story_id="story-001",
            sprint_id="sprint-001",
        )
        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 1,
                "stories_delivered": 1,
                "stories_carried": 0,
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([sprint_start, commit, sprint_end, session_end, new_event])
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(commit["id"], retained_ids)

    def test_commit_archived_after_retro_done(self):
        """Commit becomes archivable once sprint_retro_done event fires."""
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={"sprint_id": "sprint-001", "action": "start"},
        )
        commit = commit_event(
            files=["src/foo.py"],
            ts="2026-01-02T00:00:00+00:00",
            story_id="story-001",
            sprint_id="sprint-001",
        )
        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="Sprint complete",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 1,
                "stories_delivered": 1,
                "stories_carried": 0,
            },
        )
        retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events(
            [sprint_start, commit, sprint_end, retro_done, session_end, new_event]
        )
        self._set_curation_watermark(5)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(commit["id"], retained_ids)

    def test_commit_without_sprint_id_archived(self):
        """Free-mode commit (no metadata.sprint_id) gets archived as today."""
        import compact

        commit = commit_event(
            files=["src/foo.py"],
            ts="2026-01-02T00:00:00+00:00",
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([commit, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(commit["id"], retained_ids)

    def test_commit_persists_through_multiple_compactions_until_retro_done(self):
        """Multi-round: commit survives compactions; archived only after retro.

        Regression: an earlier fix retained commits via pending_retro_sprint_ids
        but archived sprint_start once a sprint_end existed. After round 2 the
        sprint_start was gone, so round 3 could not recompute pending and
        wrongly archived the commit before retro fired.
        """
        import compact

        sprint_start = make_event(
            EVENT_TYPE_SPRINT,
            content="start",
            ts="2026-01-01T00:00:00+00:00",
            metadata={"sprint_id": "sprint-001", "action": "start"},
        )
        commit = commit_event(
            files=["src/foo.py"],
            ts="2026-01-02T00:00:00+00:00",
            story_id="story-001",
            sprint_id="sprint-001",
        )
        se1 = make_event(
            EVENT_TYPE_SESSION_END,
            content="end1",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )

        # Round 1: sprint started, commit recorded
        self._write_events([sprint_start, commit, se1])
        self._set_curation_watermark(3)
        compact.compact_after_curation(self.smm_dir)
        after_round1 = self._read_events()
        self.assertIn(commit["id"], {e["id"] for e in after_round1})

        # Round 2: sprint ends but no retro yet — commit must still be retained
        sprint_end = make_event(
            EVENT_TYPE_SPRINT,
            content="end",
            ts="2026-01-05T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 1,
                "stories_delivered": 1,
                "stories_carried": 0,
            },
        )
        se2 = make_event(
            EVENT_TYPE_SESSION_END,
            content="end2",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
        )
        self._write_events([*after_round1, sprint_end, se2])
        self._set_curation_watermark(len(after_round1) + 2)
        compact.compact_after_curation(self.smm_dir)
        after_round2 = self._read_events()
        self.assertIn(commit["id"], {e["id"] for e in after_round2})

        # Round 3: another session passes, still no retro — commit still retained
        se3 = make_event(
            EVENT_TYPE_SESSION_END,
            content="end3",
            ts="2026-01-08T00:00:00+00:00",
            working_on=[],
        )
        self._write_events([*after_round2, se3])
        self._set_curation_watermark(len(after_round2) + 1)
        compact.compact_after_curation(self.smm_dir)
        after_round3 = self._read_events()
        self.assertIn(commit["id"], {e["id"] for e in after_round3})

        # Round 4: retro fires — commit may now be archived
        retro_done = make_event(
            EVENT_TYPE_STATUS,
            content="retro complete",
            ts="2026-01-09T00:00:00+00:00",
            working_on=[],
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
        )
        se4 = make_event(
            EVENT_TYPE_SESSION_END,
            content="end4",
            ts="2026-01-10T00:00:00+00:00",
            working_on=[],
        )
        self._write_events([*after_round3, retro_done, se4])
        self._set_curation_watermark(len(after_round3) + 2)
        compact.compact_after_curation(self.smm_dir)
        after_round4 = self._read_events()
        self.assertNotIn(commit["id"], {e["id"] for e in after_round4})


if __name__ == "__main__":
    unittest.main()
