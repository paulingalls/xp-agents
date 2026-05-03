#!/usr/bin/env python3
"""Tests for curation-watermark-based compaction: basic operations.

Sprint lifecycle and team safety tests in test_compact_curation_sprint.py.
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
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_SESSION_END,
    EVENT_TYPE_STATUS,
)


class TestCompactAfterCuration(_SMMTestCase):
    """Tests for curation-watermark-based compaction."""

    def _make_session(self, event_count: int = 3, session_num: int = 1) -> list[dict]:
        """Create a session: N events + session_end."""
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
        """Write a curation watermark at the given event count."""
        materialize.write_curation_watermark(self.smm_dir, event_count, agent_id)

    def test_keeps_events_after_curation_watermark(self):
        """Events past the curation watermark are always retained."""
        import compact

        old = self._make_session(session_num=1)
        new = self._make_session(session_num=2)
        self._write_events(old + new)
        self._set_curation_watermark(len(old))

        result = compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_contents = [e.get("content", "") for e in retained]
        for e in new:
            self.assertIn(e["content"], retained_contents)
        self.assertGreater(result["archived"], 0)

    def test_keeps_last_3_session_ends(self):
        """Last 3 session_end events retained for aging calculations."""
        import compact

        all_events = []
        for s in range(1, 7):
            all_events.extend(self._make_session(session_num=s))
        self._write_events(all_events)
        wm = sum(4 for _ in range(5))
        self._set_curation_watermark(wm)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        session_ends = [e for e in retained if e.get("type") == EVENT_TYPE_SESSION_END]
        pre_wm_ends = [
            e for e in session_ends if e.get("content", "") != "end session 6"
        ]
        self.assertGreaterEqual(len(pre_wm_ends), 3)

    def test_keeps_smm_referenced_events(self):
        """Unresolved goals, active decisions, open concerns are retained."""
        import compact

        goal = make_event(
            EVENT_TYPE_GOAL, content="Ship v1", ts="2026-01-01T00:00:00+00:00"
        )
        decision = make_event(
            EVENT_TYPE_DECISION,
            content="Use Postgres",
            topic="db",
            ts="2026-01-01T00:00:00+00:00",
        )
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="No tests",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event(
            EVENT_TYPE_STATUS, content="working", ts="2026-01-01T00:00:00+00:00"
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
        )
        self._write_events([goal, decision, concern, filler, session_end])
        self._set_curation_watermark(5)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(goal["id"], retained_ids)
        self.assertIn(decision["id"], retained_ids)
        self.assertIn(concern["id"], retained_ids)
        self.assertNotIn(filler["id"], retained_ids)

    def test_archives_resolved_permanent_before_watermark(self):
        """Resolved goal before watermark is archivable (new policy)."""
        import compact

        goal = make_event(
            EVENT_TYPE_GOAL, content="Ship v1", ts="2026-01-01T00:00:00+00:00"
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Goal completed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [goal["id"]]},
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new work", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([goal, resolution, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(goal["id"], retained_ids)

    def test_unresolved_assumption_retained(self):
        """Unresolved assumptions are still retained (active risk)."""
        import compact

        assumption = make_event(
            EVENT_TYPE_ASSUMPTION,
            content="API returns JSON",
            ts="2026-01-01T00:00:00+00:00",
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS,
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
        """Resolved assumptions are archivable."""
        import compact

        assumption = make_event(
            EVENT_TYPE_ASSUMPTION,
            content="API returns JSON",
            ts="2026-01-01T00:00:00+00:00",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Verified: API returns JSON",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [assumption["id"]]},
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        new_event = make_event(
            EVENT_TYPE_STATUS,
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

        goal = make_event(
            EVENT_TYPE_GOAL, content="Ship v1", ts="2026-01-01T00:00:00+00:00"
        )
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Open issue", ts="2026-01-01T00:00:00+00:00"
        )
        partial_resolution = make_event(
            EVENT_TYPE_STATUS,
            content="Partially addressed",
            ts="2026-01-02T00:00:00+00:00",
            metadata={"resolves": [concern["id"]]},
        )
        session_end = make_event(
            EVENT_TYPE_SESSION_END,
            content="end",
            ts="2026-01-03T00:00:00+00:00",
            working_on=[],
        )
        self._write_events([goal, concern, partial_resolution, session_end])
        self._set_curation_watermark(4)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(goal["id"], retained_ids)
        self.assertNotIn(concern["id"], retained_ids)
        self.assertNotIn(partial_resolution["id"], retained_ids)

    def test_creates_backup_archive(self):
        """Archived events written to backups/ directory."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
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

        goal = make_event(
            EVENT_TYPE_GOAL, content="first", ts="2026-01-01T00:00:00+00:00"
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
        self._write_events([goal, session_end, new_event])
        self._set_curation_watermark(2)

        compact.compact_after_curation(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        self.assertEqual(ids[0], goal["id"])

    def test_no_watermark_keeps_all(self):
        """No curation watermark = no compaction."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)

        result = compact.compact_after_curation(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        retained = self._read_events()
        self.assertEqual(len(retained), len(events))

    def test_resets_prompt_nugget_watermark(self):
        """Prompt-nugget watermark set to post-compaction event count."""
        import compact

        all_events = self._make_session(session_num=1)
        new_event = make_event(
            EVENT_TYPE_STATUS, content="new", ts="2026-02-01T00:00:00+00:00"
        )
        self._write_events([*all_events, new_event])
        (self.smm_dir / ".watermark-prompt-nugget").write_text("100")
        self._set_curation_watermark(len(all_events))

        result = compact.compact_after_curation(self.smm_dir)
        self.assertGreater(result["archived"], 0)
        wm_text = (self.smm_dir / ".watermark-prompt-nugget").read_text().strip()
        self.assertEqual(int(wm_text), result["retained"])

    def test_updates_curation_watermark(self):
        """Curation watermark event_count updated after compaction."""
        import compact

        goal = make_event(
            EVENT_TYPE_GOAL, content="Keep me", ts="2026-01-01T00:00:00+00:00"
        )
        filler = make_event(
            EVENT_TYPE_STATUS, content="discard", ts="2026-01-01T00:00:00+00:00"
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
        self._write_events([goal, filler, session_end, new_event])
        self._set_curation_watermark(3)

        compact.compact_after_curation(self.smm_dir)
        wm = materialize.read_curation_watermark(self.smm_dir)
        retained = self._read_events()
        post_wm_count = 1
        self.assertEqual(wm["event_count"], len(retained) - post_wm_count)

    def test_removes_orphaned_watermarks(self):
        """Orphaned .watermark-{hex} files removed, prompt-nugget preserved."""
        import compact

        self._write_events(self._make_session(session_num=1))
        self._set_curation_watermark(4)
        (self.smm_dir / ".watermark-abc123").write_text("5")
        (self.smm_dir / ".watermark-main").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact_after_curation(self.smm_dir)
        self.assertFalse((self.smm_dir / ".watermark-abc123").exists())
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())
        self.assertTrue((self.smm_dir / ".curation-watermark").exists())

    def test_reads_events_under_lock(self):
        """compact_after_curation uses read_with_lock, not unlocked read_text."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        self._set_curation_watermark(len(events))

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

        all_events = []
        for s in range(1, 4):
            all_events.extend(self._make_session(session_num=s))
        post = make_event(
            EVENT_TYPE_STATUS, content="post", ts="2026-03-04T00:00:00+00:00"
        )
        all_events.append(post)
        self._write_events(all_events)

        self._set_curation_watermark(4)
        wm_a = self.smm_dir / ".curation-watermark-agent-a"
        wm_a.write_text(json.dumps({"event_count": 8, "agent_id": "agent-a"}))

        result = compact.compact_after_curation(self.smm_dir)
        archived = result["archived"]
        self.assertGreater(archived, 0)

        wm_a_data = json.loads(wm_a.read_text())
        self.assertEqual(wm_a_data["event_count"], 8 - archived)


if __name__ == "__main__":
    unittest.main()
