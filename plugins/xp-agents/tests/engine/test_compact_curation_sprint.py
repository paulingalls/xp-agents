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
from conftest import _SMMTestCase, make_event


class TestCompactCurationTeamAndSprint(_SMMTestCase):
    """Tests for team watermark handling and sprint event compaction."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        ts_base = f"2026-03-{session_num:02d}T00:00:00+00:00"
        events = [
            make_event(
                "customer_input",
                content=f"session {session_num} event {i}",
                ts=ts_base,
            )
            for i in range(event_count)
        ]
        events.append(
            make_event(
                "session_end",
                content=f"end session {session_num}",
                ts=ts_base,
                working_on=[],
            )
        )
        return events

    def _set_curation_watermark(
        self, event_count: int, agent_id: str = "xp-housekeeping"
    ):
        materialize.write_curation_watermark(self.smm_dir, event_count, agent_id)

    def test_team_safety_uses_oldest_watermark(self):
        """With multiple curation watermarks, uses min(event_count)."""
        import compact

        all_events = []
        for i in range(1, 4):
            all_events.extend(self._make_session(session_num=i))
        filler = make_event("status", content="filler", ts="2026-04-01T00:00:00+00:00")
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
            "sprint",
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={
                "sprint_id": "sprint-001",
                "action": "start",
                "goal": "Build user API",
            },
        )
        session_end = make_event(
            "session_end",
            content="end",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([sprint_start, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_start["id"], retained_ids)

    def test_archives_ended_sprint_start(self):
        """Sprint start is archived when a matching end event exists."""
        import compact

        sprint_start = make_event(
            "sprint",
            content="Build user API",
            ts="2026-01-01T00:00:00+00:00",
            metadata={"sprint_id": "sprint-001", "action": "start"},
        )
        sprint_end = make_event(
            "sprint",
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
            "session_end",
            content="end",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([sprint_start, sprint_end, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(sprint_start["id"], retained_ids)

    def test_retains_latest_sprint_end(self):
        """Most recent sprint end retained for velocity data."""
        import compact

        sprint_end = make_event(
            "sprint",
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
            "session_end",
            content="end",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
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
            "sprint",
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
            "sprint",
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
            "session_end",
            content="end",
            ts="2026-01-16T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
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
            "sprint",
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
            "status",
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        session_end = make_event(
            "session_end",
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
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
            "sprint",
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
            "status",
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        sprint_end_new = make_event(
            "sprint",
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
            "session_end",
            content="end",
            ts="2026-01-16T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
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
            "sprint",
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
            "status",
            content="Sprint retrospective complete.",
            ts="2026-01-06T00:00:00+00:00",
            working_on=[],
            metadata={
                "sprint_id": "sprint-001",
                "action": "sprint_retro_done",
            },
        )
        session_end = make_event(
            "session_end",
            content="end",
            ts="2026-01-07T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
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


if __name__ == "__main__":
    unittest.main()
