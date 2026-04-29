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

    def test_session_end_content_within_budget(self):
        """session_end content must stay within 50-char budget."""
        import session_end
        from event_schema import CONTENT_BUDGETS

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "x" * 100},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        budget = CONTENT_BUDGETS["session_end"]
        self.assertLessEqual(
            len(se["content"]),
            budget,
            f"session_end content {len(se['content'])} exceeds budget {budget}",
        )

    def test_resolves_session_goal_events(self):
        """Goals from current session are resolved via metadata.resolves on
        the session_end event so compaction archives them."""
        import session_end

        g1 = make_event("goal", content="Free session", agent_id="xp-kickoff")
        g2 = make_event("goal", content="Fix the bug", agent_id="xp-work-selection")
        self._write_events([g1, g2])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        resolves = (se.get("metadata") or {}).get("resolves", [])
        self.assertIn(g1["id"], resolves)
        self.assertIn(g2["id"], resolves)

    def test_already_resolved_goals_not_re_resolved(self):
        """Goals already resolved by a prior session_end (via metadata.resolves)
        must not be re-listed in the new session_end's metadata.resolves."""
        import session_end

        prior_goal = make_event(
            "goal",
            content="Prior session goal",
            ts="2026-03-12T08:00:00+00:00",
            agent_id="xp-kickoff",
        )
        prior_end = make_event(
            "session_end",
            ts="2026-03-12T09:00:00+00:00",
            content="Session ended: prior",
            metadata={"resolves": [prior_goal["id"]]},
        )
        current_goal = make_event(
            "goal",
            content="Current session goal",
            ts="2026-03-12T10:00:00+00:00",
            agent_id="xp-kickoff",
        )
        self._write_events([prior_goal, prior_end, current_goal])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = [e for e in events if e.get("type") == "session_end"][-1]
        resolves = (se.get("metadata") or {}).get("resolves", [])
        self.assertIn(current_goal["id"], resolves)
        self.assertNotIn(prior_goal["id"], resolves)

    def test_main_session_does_not_resolve_teammate_goals(self):
        """Multi-teammate worktrees share one SMM. Main session_end must
        not claim ownership of a teammate's still-unresolved goals."""
        import session_end

        main_goal = make_event("goal", content="Main goal", agent_id="xp-kickoff")
        teammate_goal = make_event(
            "goal", content="Teammate goal", agent_id="worktree-story-001"
        )
        self._write_events([main_goal, teammate_goal])
        session_end.run(
            {"session_id": "test", "reason": "logout", "cwd": "/home/user/project"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        resolves = (se.get("metadata") or {}).get("resolves", [])
        self.assertIn(main_goal["id"], resolves)
        self.assertNotIn(teammate_goal["id"], resolves)

    def test_teammate_resolves_only_own_goals(self):
        """A teammate session_end resolves only its own teammate-prefixed
        goals — not main's goals nor other teammates' goals."""
        import session_end

        main_goal = make_event("goal", content="Main goal", agent_id="xp-kickoff")
        own_goal = make_event(
            "goal", content="Own teammate goal", agent_id="worktree-story-001"
        )
        other_goal = make_event(
            "goal", content="Other teammate goal", agent_id="worktree-story-002"
        )
        self._write_events([main_goal, own_goal, other_goal])
        session_end.run(
            {
                "session_id": "test",
                "reason": "done",
                "cwd": "/home/user/project/.claude/worktrees/worktree-story-001/src",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        resolves = (se.get("metadata") or {}).get("resolves", [])
        self.assertIn(own_goal["id"], resolves)
        self.assertNotIn(main_goal["id"], resolves)
        self.assertNotIn(other_goal["id"], resolves)

    def test_no_resolves_metadata_when_no_goals(self):
        """When no goals were emitted in the session, the session_end
        event must not carry a (possibly-empty) metadata.resolves list."""
        import session_end

        self._write_events([make_event(content="status only")])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        meta = se.get("metadata") or {}
        self.assertNotIn("resolves", meta)


# ===========================================================================
# Teammate SessionEnd tests
# ===========================================================================


class TestTeammateSessionEnd(_HookTestCase):
    """CLI teammate SessionEnd: resolve_agent_id + completion event."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def test_resolve_agent_id_used_in_event(self):
        """SessionEnd event uses resolve_agent_id, not hardcoded 'main'."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertEqual(se["agent_id"], "worktree-story-001")

    def test_non_teammate_uses_main(self):
        """Non-teammate SessionEnd still uses 'main' agent_id."""
        import session_end

        self._write_events([make_event()])
        session_end.run(
            {"session_id": "test", "reason": "done", "cwd": "/home/user/project"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
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
        events = _common.read_events_raw(self.smm_dir)
        statuses = [
            e
            for e in events
            if e.get("type") == "status"
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
        events = _common.read_events_raw(self.smm_dir)
        statuses = [
            e
            for e in events
            if e.get("type") == "status" and "completed" in e.get("content", "").lower()
        ]
        self.assertEqual(len(statuses), 0)


if __name__ == "__main__":
    unittest.main()
