#!/usr/bin/env python3
"""Tests for session lifecycle hooks: session_end and pre_compact.

Kickoff tests (kickoff_gate, kickoff_done) in test_kickoff.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import _HookTestCase, make_event

# ===========================================================================
# session_end.py tests
# ===========================================================================


class TestSessionEnd(_HookTestCase):
    def test_xp_agent_skips(self):
        import session_end

        result = session_end.run(
            {"session_id": "test", "reason": "logout", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_missing_smm_dir(self):
        import session_end

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_appends_session_end_event(self):
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        session_ends = [e for e in events if e.get("type") == "session_end"]
        self.assertEqual(len(session_ends), 1)

    def test_event_count_in_session_end(self):
        import session_end

        self._write_events([make_event(), make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertEqual(se["event_count"], 2)

    def test_unresolved_questions(self):
        import session_end

        q = make_event("question", content="Unanswered?")
        self._write_events([q])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn(q["id"], se["unresolved_items"])

    def test_answered_question_not_unresolved(self):
        import session_end

        q = make_event("question", content="Answered!")
        a = make_event("answer", content="Yes", references=[q["id"]])
        self._write_events([q, a])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertNotIn(q["id"], se["unresolved_items"])

    def test_unresolved_concerns(self):
        import session_end

        c = make_event("concern", content="Missing tests")
        self._write_events([c])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn(c["id"], se["unresolved_items"])

    def test_resolved_concern_not_unresolved(self):
        import session_end

        c = make_event("concern", content="Missing tests")
        r = make_event(
            "status",
            content="Fixed",
            working_on=["test.py"],
            metadata={"resolves": [c["id"]]},
        )
        self._write_events([c, r])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertNotIn(c["id"], se["unresolved_items"])

    def test_active_working_on(self):
        import session_end

        s = make_event("status", agent_id="main", working_on=["src/app.ts"])
        self._write_events([s])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn("src/app.ts", se["working_on"])

    def test_final_status_always_true(self):
        """session_end event IS the final status — always true."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertTrue(se["final_status_recorded"])

    def test_empty_events(self):
        import session_end

        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertEqual(se["event_count"], 0)
        self.assertEqual(se["unresolved_items"], [])

    def test_duration_seconds_present(self):
        """AC: SessionEnd captures all summary fields — including duration."""
        import session_end

        # Write events with timestamps spanning a period
        e1 = make_event(ts="2026-03-12T10:00:00+00:00")
        e2 = make_event(ts="2026-03-12T10:05:00+00:00")
        self._write_events([e1, e2])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn("duration_seconds", se)
        self.assertIsInstance(se["duration_seconds"], (int, float))
        self.assertGreater(se["duration_seconds"], 0)

    def test_duration_after_previous_session_end(self):
        """Duration should only count from events after the last session_end."""
        import session_end

        # Previous session's events + session_end
        old = make_event(ts="2026-03-12T08:00:00+00:00")
        old_end = make_event(
            "session_end", ts="2026-03-12T09:00:00+00:00", content="old"
        )
        # Current session's events
        new1 = make_event(ts="2026-03-12T10:00:00+00:00")
        new2 = make_event(ts="2026-03-12T10:30:00+00:00")
        self._write_events([old, old_end, new1, new2])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se_events = [e for e in events if e.get("type") == "session_end"]
        se = se_events[-1]  # Get the one we just appended
        # Duration based on current session (10:00 to now), not 08:00
        # At minimum it should be > 0 (since now > 10:30)
        self.assertGreater(se["duration_seconds"], 0)

    def test_reason_in_content(self):
        """AC: SessionEnd captures reason."""
        import session_end

        session_end.run(
            {"session_id": "test", "reason": "user_logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn("user_logout", se["content"])

    def test_clears_lint_warned(self):
        """SessionEnd should remove .lint-warned so nudge re-fires next session."""
        import session_end

        (self.smm_dir / ".lint-warned").touch()
        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".lint-warned").exists())

    def test_clears_agent_scoped_markers(self):
        """SessionEnd should remove TDD tracker and review cycle markers."""
        import markers
        import session_end

        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, "main")
        markers.marker_write(
            self.smm_dir, markers.REVIEW_CYCLE, {"last_review_commit": ""}, "main"
        )

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "main")
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.REVIEW_CYCLE, "main")
        )


# ===========================================================================
# pre_compact.py tests
# ===========================================================================


class TestPreCompact(_HookTestCase):
    def test_xp_agent_skips(self):
        import pre_compact

        result = pre_compact.run(
            {"session_id": "test", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_missing_smm_dir(self):
        import pre_compact

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = pre_compact.run(
            {"session_id": "test"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_creates_backup_of_events(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backups = list((self.smm_dir / "backups").glob("events-*.jsonl"))
        self.assertEqual(len(backups), 1)

    def test_creates_backup_of_smm(self):
        import pre_compact

        self._write_events([make_event()])
        smm_md = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_md.write_text("# Test SMM")
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backups = list((self.smm_dir / "backups").glob("SMM-*.md"))
        self.assertEqual(len(backups), 1)

    def test_backup_content_matches(self):
        import pre_compact

        events = [make_event()]
        self._write_events(events)
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backup = next(iter((self.smm_dir / "backups").glob("events-*.jsonl")))
        original = self.events_file.read_text()
        self.assertEqual(backup.read_text(), original)

    def test_no_smm_file_only_events_backed_up(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        event_backups = list((self.smm_dir / "backups").glob("events-*.jsonl"))
        smm_backups = list((self.smm_dir / "backups").glob("SMM-*.md"))
        self.assertEqual(len(event_backups), 1)
        self.assertEqual(len(smm_backups), 0)

    def test_timestamp_in_backup_name(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backup = next(iter((self.smm_dir / "backups").glob("events-*.jsonl")))
        # Name should be events-YYYYMMDD-HHMMSS.jsonl
        name = backup.stem  # events-YYYYMMDD-HHMMSS
        parts = name.split("-", 1)
        self.assertEqual(parts[0], "events")
        self.assertTrue(len(parts[1]) > 0)

    def test_backup_rotation_caps_old_backups(self):
        import pre_compact

        self._write_events([make_event()])
        backups_dir = self.smm_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        # Create 12 fake old backups
        for i in range(12):
            (backups_dir / f"events-20250101-{i:06d}.jsonl").write_text("old")
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        # After rotation, should have at most _MAX_BACKUPS (10)
        remaining = list(backups_dir.glob("events-*.jsonl"))
        self.assertLessEqual(len(remaining), pre_compact._MAX_BACKUPS)


if __name__ == "__main__":
    unittest.main()
