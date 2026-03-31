#!/usr/bin/env python3
"""Tests for compaction logic (legacy compact entry point).

Curation-watermark-based compaction tests in test_compact_curation.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
from conftest import _SMMTestCase, make_event

# ===========================================================================
# Compact (Milestone 8)
# ===========================================================================


class TestCompact(_SMMTestCase):
    """Tests for compact() legacy entry point (delegates to compact_after_curation)."""

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

    def test_compact_empty_log(self):
        import compact

        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 0)

    def test_compact_delegates_to_compact_after_curation(self):
        """compact() uses curation-watermark-based retention via delegation."""
        import compact

        goal = make_event("goal", content="keep me", ts="2026-01-01T00:00:00+00:00")
        filler = make_event("status", content="discard", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([goal, filler, session_end, new_event])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        result = compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        # Unresolved goal retained (SMM-referenced)
        self.assertIn(goal["id"], retained_ids)
        # Filler archived
        self.assertNotIn(filler["id"], retained_ids)
        # Return has legacy keys
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)

    def test_compact_unresolved_questions_retained(self):
        """Unresolved questions retained via SMM-referenced policy."""
        import compact

        q = make_event(
            "question",
            content="Unanswered?",
            priority="\U0001f534",
            ts="2026-01-01T00:00:00+00:00",
        )
        filler = make_event("status", content="filler", ts="2026-01-01T00:00:00+00:00")
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([q, filler, session_end])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(q["id"], retained_ids)

    def test_compact_resolved_questions_archivable(self):
        """Resolved questions before watermark can be archived."""
        import compact

        q = make_event(
            "question",
            content="Answered",
            priority="\U0001f534",
            ts="2026-01-01T00:00:00+00:00",
        )
        a = make_event(
            "answer",
            content="Yes",
            references=[q["id"]],
            ts="2026-01-01T00:00:01+00:00",
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([q, a, session_end])
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertNotIn(q["id"], retained_ids)

    def test_compact_unresolved_concerns_retained(self):
        """Unresolved concerns retained via SMM-referenced policy."""
        import compact

        c = make_event(
            "concern", content="Unresolved concern", ts="2026-01-01T00:00:00+00:00"
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        self._write_events([c, session_end])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        retained_ids = {e["id"] for e in retained}
        self.assertIn(c["id"], retained_ids)

    def test_compact_creates_archive(self):
        """Archived events written to backups/archive-{ts}.jsonl."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeping")

        compact.compact(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        archives = list(backups.glob("archive-*.jsonl"))
        self.assertEqual(len(archives), 1)
        archive_text = archives[0].read_text().strip()
        self.assertGreater(len(archive_text), 0)

    def test_compact_removes_orphaned_watermarks(self):
        """Orphaned .watermark-* files removed, prompt-nugget reset."""
        import compact

        self._write_events(self._make_session(session_num=1))
        materialize.write_curation_watermark(self.smm_dir, 4, "xp-housekeeping")
        (self.smm_dir / ".watermark-main").write_text("5")
        (self.smm_dir / ".watermark-housekeeping").write_text("3")
        (self.smm_dir / ".watermark-prompt-nugget").write_text("10")

        compact.compact(self.smm_dir)
        # Orphaned removed
        self.assertFalse((self.smm_dir / ".watermark-main").exists())
        self.assertFalse((self.smm_dir / ".watermark-housekeeping").exists())
        # Prompt-nugget preserved with updated value
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())

    def test_compact_atomic_replacement(self):
        """events.jsonl is replaced atomically (not corrupted on crash)."""
        import compact

        events = self._make_session(session_num=1)
        self._write_events(events)
        materialize.write_curation_watermark(
            self.smm_dir, len(events), "xp-housekeeping"
        )
        compact.compact(self.smm_dir)
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)  # Should not raise

    def test_compact_no_watermark_no_archival(self):
        """Without curation watermark, nothing is archived."""
        import compact

        self._write_events(self._make_session(session_num=1))
        result = compact.compact(self.smm_dir)
        self.assertEqual(result["archived"], 0)

    def test_compact_returns_counts(self):
        """Return dict has archived, retained, permanent keys."""
        import compact

        old = self._make_session(session_num=1)
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([*old, new_event])
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeping")

        result = compact.compact(self.smm_dir)
        self.assertIn("archived", result)
        self.assertIn("retained", result)
        self.assertIn("permanent", result)
        self.assertEqual(
            result["archived"] + result["retained"],
            len(old) + 1,
        )

    def test_compact_preserves_event_order(self):
        """Retained events maintain original order."""
        import compact

        decision = make_event(
            "decision", content="first", topic="t", ts="2026-01-01T00:00:00+00:00"
        )
        session_end = make_event(
            "session_end", content="end", ts="2026-01-02T00:00:00+00:00", working_on=[]
        )
        new_event = make_event("status", content="new", ts="2026-02-01T00:00:00+00:00")
        self._write_events([decision, session_end, new_event])
        materialize.write_curation_watermark(self.smm_dir, 2, "xp-housekeeping")

        compact.compact(self.smm_dir)
        retained = self._read_events()
        ids = [e["id"] for e in retained]
        self.assertEqual(ids[0], decision["id"])


if __name__ == "__main__":
    unittest.main()
