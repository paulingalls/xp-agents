#!/usr/bin/env python3
"""Tests for session_end.py — session summary and goal resolution.

Pre-compact tests in test_pre_compact.py; kickoff gate tests in
test_kickoff.py; housekeeping handler tests in test_subagent.py::
TestHousekeepingDone.
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
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_ANSWER,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_SESSION_END,
    EVENT_TYPE_STATUS,
)

_WATERMARK_ID = "test-session-lifecycle"

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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        session_ends = events_of_type(events, EVENT_TYPE_SESSION_END)
        self.assertEqual(len(session_ends), 1)

    def test_event_count_in_session_end(self):
        import session_end

        self._write_events([make_event(), make_event()])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertEqual(se["event_count"], 2)

    def test_unresolved_questions(self):
        import session_end

        q = make_event(EVENT_TYPE_QUESTION, content="Unanswered?")
        self._write_events([q])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertIn(q["id"], se["unresolved_items"])

    def test_answered_question_not_unresolved(self):
        import session_end

        q = make_event(EVENT_TYPE_QUESTION, content="Answered!")
        a = make_event(EVENT_TYPE_ANSWER, content="Yes", references=[q["id"]])
        self._write_events([q, a])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertNotIn(q["id"], se["unresolved_items"])

    def test_unresolved_concerns(self):
        import session_end

        c = make_event(EVENT_TYPE_CONCERN, content="Missing tests")
        self._write_events([c])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertIn(c["id"], se["unresolved_items"])

    def test_resolved_concern_not_unresolved(self):
        import session_end

        c = make_event(EVENT_TYPE_CONCERN, content="Missing tests")
        r = make_event(
            EVENT_TYPE_STATUS,
            content="Fixed",
            working_on=["test.py"],
            metadata={"resolves": [c["id"]]},
        )
        self._write_events([c, r])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertNotIn(c["id"], se["unresolved_items"])

    def test_active_working_on(self):
        import session_end

        s = make_event(EVENT_TYPE_STATUS, agent_id="main", working_on=["src/app.ts"])
        self._write_events([s])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertIn("src/app.ts", se["working_on"])

    def test_empty_events(self):
        import session_end

        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertIn("duration_seconds", se)
        self.assertIsInstance(se["duration_seconds"], (int, float))
        self.assertGreater(se["duration_seconds"], 0)

    def test_duration_after_previous_session_end(self):
        """Duration should only count from events after the last session_end."""
        import session_end

        # Previous session's events + session_end
        old = make_event(ts="2026-03-12T08:00:00+00:00")
        old_end = make_event(
            EVENT_TYPE_SESSION_END, ts="2026-03-12T09:00:00+00:00", content="old"
        )
        # Current session's events
        new1 = make_event(ts="2026-03-12T10:00:00+00:00")
        new2 = make_event(ts="2026-03-12T10:30:00+00:00")
        self._write_events([old, old_end, new1, new2])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se_events = events_of_type(events, EVENT_TYPE_SESSION_END)
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
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

    def test_session_end_content_within_budget(self):
        """session_end content must stay within 50-char budget."""
        import session_end
        from event_schema import get_required_budget

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "x" * 100},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        budget = get_required_budget(EVENT_TYPE_SESSION_END)
        self.assertLessEqual(
            len(se["content"]),
            budget,
            f"session_end content {len(se['content'])} exceeds budget {budget}",
        )

    def test_session_end_never_emits_resolves_metadata(self):
        """Goal resolution moved off session_end to SessionStart (M3,
        story-002). Even with main- and teammate-owned goals open in the
        log, session_end must not carry metadata.resolves for goals."""
        import session_end

        g_main = make_event(EVENT_TYPE_GOAL, content="Main goal", agent_id="xp-kickoff")
        g_team = make_event(
            EVENT_TYPE_GOAL, content="Teammate goal", agent_id="worktree-story-001"
        )
        self._write_events([g_main, g_team])
        session_end.run(
            {"session_id": "test", "reason": "logout", "cwd": "/home/user/project"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertNotIn("resolves", se.get("metadata") or {})

    def test_no_resolves_metadata_when_no_goals(self):
        """When no goals were emitted in the session, the session_end
        event must not carry a (possibly-empty) metadata.resolves list."""
        import session_end

        self._write_events([make_event(content="status only")])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        meta = se.get("metadata") or {}
        self.assertNotIn("resolves", meta)

    def test_session_end_emits_no_stale_flags(self):
        """Stale-concern sweep moved off session_end to SessionStart (M3,
        story-002). A concern old enough to once trip the sweep must NOT
        produce a flagged_stale concern from session_end anymore."""
        import session_end

        c = make_event(EVENT_TYPE_CONCERN, content="Old concern")
        self._write_events(
            [
                c,
                make_event(EVENT_TYPE_SESSION_END, content="Session ended: s1"),
                make_event(EVENT_TYPE_SESSION_END, content="Session ended: s2"),
                make_event(EVENT_TYPE_SESSION_END, content="Session ended: s3"),
                make_event(EVENT_TYPE_SESSION_END, content="Session ended: s4"),
            ]
        )
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        flags = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_CONCERN
            and (e.get("metadata") or {}).get("flagged_stale") is True
        ]
        self.assertEqual(flags, [])

    def test_duration_spans_full_conversation_when_no_session_started_anchor(self):
        """Concern 4b7a27898de7: with no session_started anchor (e.g. a
        resume/compact continuation), duration anchors on the original
        first event — the resumed session is logically one session."""
        import session_end

        old = make_event(content="early", ts="2026-03-12T08:00:00+00:00")
        recent = make_event(content="late", ts="2026-03-12T10:00:00+00:00")
        self._write_events([old, recent])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        # Anchored at the 08:00 first event, so duration spans from then to
        # now (well over the 2h gap to the 10:00 event), not just the tail.
        self.assertGreater(se["duration_seconds"], 7200)

    def test_duration_anchors_at_tail_cap_when_no_anchor_and_long_log(self):
        """Concern 4b7a27898de7: a no-anchor log longer than the tail cap
        anchors at len - _NO_ANCHOR_TAIL_CAP, deliberately bounding an
        unbounded 'current session' rather than swallowing the whole log."""
        import session_end

        cap = _common._NO_ANCHOR_TAIL_CAP
        # cap+5 events, none of them a session_started anchor.
        long_log = [make_event(content=f"e{i}") for i in range(cap + 5)]
        self._write_events(long_log)
        events_before = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(
            _common.current_session_start_index(events_before),
            len(events_before) - cap,
        )
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        # session_end still appends exactly one summary event.
        after = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events_of_type(after, EVENT_TYPE_SESSION_END)), 1)


# ===========================================================================
# Teammate SessionEnd tests
# ===========================================================================


class TestTeammateSessionEnd(_HookTestCase):
    """CLI teammate SessionEnd: resolve_agent_id + completion event."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def test_teammate_emits_no_session_end(self):
        """A worktree teammate shares main's session window with no anchor
        of its own, so a per-teammate session_end only corrupts boundary
        counts (M3). The teammate emits a completion status instead."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(events_of_type(events, EVENT_TYPE_SESSION_END), [])

    def test_teammate_completion_uses_resolved_agent_id(self):
        """The teammate completion status uses resolve_agent_id, not a
        hardcoded 'main' — preserves identity-resolution coverage."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        completions = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and "completed" in e.get("content", "").lower()
        ]
        self.assertEqual(len(completions), 1)
        self.assertEqual(completions[0]["agent_id"], "worktree-story-001")

    def test_non_teammate_uses_main(self):
        """Non-teammate SessionEnd still uses 'main' agent_id."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": "/home/user/project"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        se = events_of_type(events, EVENT_TYPE_SESSION_END)[0]
        self.assertEqual(se["agent_id"], "main")

    def test_cleanup_uses_resolved_agent_id(self):
        """Marker cleanup uses resolved agent_id, not hardcoded 'main'."""
        import markers
        import session_end

        agent_id = "worktree-story-001"
        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, agent_id)
        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, agent_id)
        )

    def test_teammate_records_completion_status(self):
        """Teammate SessionEnd records a status event with branch metadata."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and e.get("agent_id") == "worktree-story-001"
            and "completed" in e.get("content", "").lower()
        ]
        self.assertEqual(len(statuses), 1)
        self.assertIn("branch", statuses[0].get("metadata", {}))

    def test_non_teammate_no_completion_status(self):
        """Non-teammate SessionEnd does NOT record a completion status."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": "/home/user/project"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        statuses = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and "completed" in e.get("content", "").lower()
        ]
        self.assertEqual(len(statuses), 0)


if __name__ == "__main__":
    unittest.main()
