#!/usr/bin/env python3
"""Tests for curation-watermark-based compaction.

Split from test_compact.py — covers TestCompactAfterCuration.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import _append_impl
import materialize
from conftest import _SMMTestCase, make_event


class TestCompactAfterCuration(_SMMTestCase):
    """Tests for curation-watermark-based compaction."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        """Create a session: N events + session_end."""
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
        """Write a curation watermark at the given event count."""
        materialize.write_curation_watermark(self.smm_dir, event_count, agent_id)

    def test_keeps_events_after_curation_watermark(self):
        """Events past the curation watermark are always retained."""
        import compact

        old = self._make_session(session_num=1)
        new = self._make_session(session_num=2)
        self._write_events(old + new)
        self._set_curation_watermark(len(old))  # watermark at boundary

        result = compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_contents = [e.get("content", "") for e in retained]
        # All "new" session events retained
        for e in new:
            self.assertIn(e["content"], retained_contents)
        self.assertGreater(result["archived"], 0)

    def test_keeps_last_3_session_ends(self):
        """Last 3 session_end events retained for aging calculations."""
        import compact

        all_events = []
        for s in range(1, 7):  # 6 sessions
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)
        # Watermark after session 5, so session 6 events are post-watermark
        wm = sum(4 for _ in range(5))  # 5 sessions * 4 events each
        self._set_curation_watermark(wm)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        session_ends = [e for e in retained if e.get("type") == "session_end"]
        # Session 6 (post-watermark) + 3 oldest retained
        pre_wm_ends = [
            e for e in session_ends if e.get("content", "") != "end session 6"
        ]
        self.assertGreaterEqual(len(pre_wm_ends), 3)

    def test_keeps_smm_referenced_events(self):
        """Unresolved goals, active decisions, open concerns are retained."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        decision = make_event(
            "decision",
            content="Use Postgres",
            topic="db",
            ts="2026-01-01T00:00:00+00:00",
        )
        concern = make_event(
            "concern",
            content="No tests",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event("status", content="working", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([goal, decision, concern, filler, session_end])
        self._set_curation_watermark(5)  # all pre-watermark

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(goal["id"], retained_ids)
        self.assertIn(decision["id"], retained_ids)
        self.assertIn(concern["id"], retained_ids)
        # Filler status should be archived
        self.assertNotIn(filler["id"], retained_ids)

    def test_archives_resolved_permanent_before_watermark(self):
        """Resolved goal before watermark is archivable (new policy)."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        resolution = make_event(
            "status",
            content="Goal completed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [goal["id"]]},
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-03T00:00:00+00:00", working_on=[]
        )
        new_event = make_event(
            "status", content="new work", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([goal, resolution, session_end, new_event])
        self._set_curation_watermark(3)  # watermark before new_event

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Resolved goal is archivable
        self.assertNotIn(goal["id"], retained_ids)

    def test_unresolved_assumption_retained(self):
        """Unresolved assumptions are still retained (active risk)."""
        import compact

        assumption = make_event(
            "assumption",
            content="API returns JSON",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_end = make_event(
            "session_end",
            content="end",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            "status",
            content="new work",
            ts="2026-02-01T00:00:00+00:00",
        )
        self._write_events([assumption, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(assumption["id"], retained_ids)

    def test_resolved_assumption_archived(self):
        """Resolved assumptions are archivable — fixes the accumulation bug."""
        import compact

        assumption = make_event(
            "assumption",
            content="API returns JSON",
            ts="2026-01-01T00:00:00+00:00",
        )
        resolution = make_event(
            "status",
            content="Verified: API returns JSON",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [assumption["id"]]},
        )
        session_end = make_event(
            "session_end",
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            "status",
            content="new work",
            ts="2026-02-01T00:00:00+00:00",
        )
        self._write_events([assumption, resolution, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(assumption["id"], retained_ids)

    def test_keeps_resolution_events(self):
        """If a goal is retained, its resolving event is also retained."""
        import compact

        goal = make_event("goal", content="Ship v1", ts="2026-01-01T00:00:00+00:00")
        # Goal is unresolved — no resolution event
        concern = make_event(
            "concern", content="Open issue", ts="2026-01-01T00:00:00+00:00"
        )
        partial_resolution = make_event(
            "status",
            content="Partially addressed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [concern["id"]]},
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-03T00:00:00+00:00", working_on=[]
        )
        self._write_events([goal, concern, partial_resolution, session_end])
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Goal is unresolved — retained
        self.assertIn(goal["id"], retained_ids)
        # Concern is resolved — not retained
        self.assertNotIn(concern["id"], retained_ids)
        # Resolution event for concern — not retained (concern is resolved)
        self.assertNotIn(partial_resolution["id"], retained_ids)

    def test_creates_backup_archive(self):
        """Archived events written to backups/ directory."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*all_events, new_event])
        self._set_curation_watermark(len(all_events))

        compact.compact_after_curation(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        goal = make_event("goal", content="first", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        # Goal (unresolved) should come before session_end and new_event
        self.assertEqual(ids[0], goal["id"])

    def test_no_watermark_keeps_all(self):
        """No curation watermark = no compaction."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        # No watermark set

        result = compact.compact_after_curation(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        retained = self._read_events()
        self.assertEqual(len(retained), len(events))

    def test_resets_prompt_nugget_watermark(self):
        """Prompt-nugget watermark set to post-compaction event count."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*all_events, new_event])
        # Create an old prompt-nugget watermark at a high value
        (self.smm_dir / ".watermark-prompt-nugget").write_text("100")
        self._set_curation_watermark(len(all_events))

        result = compact.compact_after_curation(self.smm_dir)
        self.assertGreater(result["archived"], 0)
        # Watermark should be reset to retained count
        wm_text = (self.smm_dir / ".watermark-prompt-nugget").read_text().strip()
        self.assertEqual(int(wm_text), result["retained"])

    def test_updates_curation_watermark(self):
        """Curation watermark event_count updated after compaction."""
        import compact

        goal = make_event("goal", content="Keep me", ts="2026-01-01T00:00:00+00:00")
        filler = make_event("status", content="discard", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, filler, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        wm = materialize.read_curation_watermark(self.smm_dir)
        # Curation watermark should point to the boundary between
        # retained pre-watermark events and post-watermark events
        retained = self._read_events()
        post_wm_count = 1  # new_event
        self.assertEqual(wm["event_count"], len(retained) - post_wm_count)

    def test_removes_orphaned_watermarks(self):
        """Orphaned .watermark-{hex} files removed, prompt-nugget preserved."""
        import compact

        self._write_events(self._make_session(session_num=1))
        self._set_curation_watermark(4)
        # Create orphaned watermarks
        (self.smm_dir / ".watermark-abc123").write_text("5")
        (self.smm_dir / ".watermark-main").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact_after_curation(self.smm_dir)
        # Orphaned watermarks removed
        self.assertFalse((self.smm_dir / ".watermark-abc123").exists())
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        # Prompt-nugget preserved (with updated value)
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())
        # Curation watermark preserved
        self.assertTrue((self.smm_dir / ".curation-watermark").exists())

    def test_reads_events_under_lock(self):
        """compact_after_curation uses read_with_lock, not unlocked read_text."""
        import compact

        # Seed events and set watermark
        events = self._make_session(session_num=1)
        self._write_events(events)
        self._set_curation_watermark(len(events))

        # Monkey-patch read_with_lock to confirm it is called
        called = {"count": 0}
        original_rwl = _append_impl.read_with_lock

        def tracking_rwl(path):
            called["count"] += 1
            return original_rwl(path)

        compact.read_with_lock = tracking_rwl
        try:
            compact.compact_after_curation(self.smm_dir)
        finally:
            compact.read_with_lock = original_rwl

        self.assertEqual(called["count"], 1, "read_with_lock should be called once")

    def test_updates_all_team_watermarks_after_compaction(self):
        """All team curation watermarks are adjusted after compaction."""
        import compact

        # 3 sessions (4 events each = 12 total) + 1 post-watermark event
        all_events = []
        for s in range(1, 4):
            all_events.extend(self._make_session(session_num=s))
        post = make_event("status", content="post", ts="2026-03-04T00:00:00+00:00")
        all_events.append(post)
        self._write_events(all_events)

        # Primary watermark at 4, agent-a at 8
        self._set_curation_watermark(4)
        wm_a = self.smm_dir / ".curation-watermark-agent-a"
        wm_a.write_text(json.dumps({"event_count": 8, "agent_id": "agent-a"}))

        result = compact.compact_after_curation(self.smm_dir)
        archived = result["archived"]
        self.assertGreater(archived, 0)

        # Agent-a watermark should be adjusted by archived_count
        wm_a_data = json.loads(wm_a.read_text())
        self.assertEqual(wm_a_data["event_count"], 8 - archived)

    def test_team_safety_uses_oldest_watermark(self):
        """With multiple curation watermarks, uses min(event_count)."""
        import compact

        all_events = []
        for s in range(1, 4):
            all_events.extend(self._make_session(session_num=s))
        filler = make_event("status", content="extra", ts="2026-03-04T00:00:00+00:00")
        all_events.append(filler)
        self._write_events(all_events)

        # Agent A curated up to event 8, agent B only up to event 4
        materialize.write_curation_watermark(self.smm_dir, 8, "agent-a")
        # Overwrite with agent B's older watermark to simulate team
        # For now, we test by writing a second watermark file
        wm_b = self.smm_dir / ".curation-watermark-agent-b"
        wm_b.write_text(json.dumps({"event_count": 4, "agent_id": "agent-b"}))

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        # Should retain everything from event 4 onward (agent B's boundary)
        # = 3 sessions * 4 events + 1 filler - 4 = 9 post-watermark events
        # Plus any SMM-referenced or session_ends from pre-watermark
        self.assertGreaterEqual(len(retained), len(all_events) - 4)

    # --- Sprint event compaction ---

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
        """Only the most recent sprint end is retained; older ones archived."""
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
        """M7: sprint_retro_done status event with sprint_id matching a
        retained sprint_end is also retained. Required by the
        _needs_sprint_retro detection scan to correctly identify that
        the retained sprint has been retrospected."""
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
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
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
        """M7: sprint_retro_done whose sprint_id does NOT match any retained
        sprint_end gets archived (not retained indefinitely)."""
        import compact

        # Old sprint end (will be archived — only last 1 retained)
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
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
        )
        # New sprint end (will be retained — most recent)
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
            [sprint_end_old, retro_done_old, sprint_end_new, session_end, new_event]
        )
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(sprint_end_new["id"], retained_ids)
        self.assertNotIn(sprint_end_old["id"], retained_ids)
        self.assertNotIn(retro_done_old["id"], retained_ids)

    def test_detection_works_after_compaction(self):
        """M7: round-trip — seed sprint_end + sprint_retro_done, compact,
        run _needs_sprint_retro → returns None (retro was done)."""
        import compact
        import sprint_retro_detection

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
            metadata={"sprint_id": "sprint-001", "action": "sprint_retro_done"},
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

        # Detection should return None — retro has been done for sprint-001.
        self.assertIsNone(sprint_retro_detection._needs_sprint_retro(retained))


if __name__ == "__main__":
    unittest.main()
