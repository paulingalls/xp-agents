#!/usr/bin/env python3
"""Tests for session lifecycle hooks: session_start, retrospective, session_end,
plugin config, pre_compact, session_review_gate, session_review_done.

Split from the monolithic test_hooks.py.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import _HookTestCase, _override_settings, make_event

# ===========================================================================
# session_start.py tests — path validation
# ===========================================================================


class TestSessionStartPathValidation(_HookTestCase):
    """Test session_start degrades gracefully with bad plugin root."""

    def test_nonexistent_plugin_root(self):
        import session_start

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/path"}):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=None,
            )
        # Should degrade gracefully, not crash
        self.assertIsNotNone(result)


class TestSmmDirValidation(_HookTestCase):
    """Tests for _common.validate_smm_dir."""

    def test_rejects_nonexistent(self):
        fake = Path(tempfile.mkdtemp()) / "nonexistent"
        with self.assertRaises(ValueError):
            _common.validate_smm_dir(fake)

    def test_rejects_world_writable(self):
        self.smm_dir.chmod(0o777)
        try:
            with self.assertRaises(ValueError):
                _common.validate_smm_dir(self.smm_dir)
        finally:
            self.smm_dir.chmod(0o700)

    def test_accepts_valid_dir(self):
        self.smm_dir.chmod(0o700)
        _common.validate_smm_dir(self.smm_dir)


# ===========================================================================
# session_start.py tests
# ===========================================================================


class TestSessionStart(_HookTestCase):
    def test_xp_agent_skips(self):
        import session_start

        result = session_start.run(
            {"session_id": "test", "source": "startup", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_clear_source_returns_context(self):
        """clear is a fresh start — should return GUPP + skills."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "clear"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Resume immediately", result)

    def test_clear_source_sets_marker_with_clear(self):
        """clear should set .needs-session-review marker with 'clear' content."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "clear"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-session-review"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "clear")

    def test_startup_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Shared Mental Model", result)

    def test_compact_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Shared Mental Model", result)

    def test_resume_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)

    def test_gupp_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("Resume immediately", result)

    def test_skills_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("smm-protocol", result)
        self.assertIn("xp-values", result)

    def test_no_retro_instruction_in_output(self):
        import session_start

        # Retro logic moved to retrospective.py — session_start should not
        # include retro instructions regardless of event count
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("Run a retrospective", result)
        self.assertNotIn("Action Required", result)

    def test_graceful_no_smm_dir(self):
        import session_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Mock resolve_plugin_root to prevent init.sh from resolving
        # the real project's SMM dir (which would leak a marker file)
        with patch.object(_common, "resolve_plugin_root", return_value=fake_dir):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=fake_dir,
            )
        # Should still return context even without SMM
        self.assertIsNotNone(result)

    def test_empty_events_file(self):
        import session_start

        # events.jsonl exists but is empty
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Should still return GUPP and skills even with empty SMM
        self.assertIsNotNone(result)
        self.assertIn("Resume immediately", result)

    def test_multiple_events_returns_smm(self):
        import session_start

        events = [make_event(content=f"event {i}") for i in range(10)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("Shared Mental Model", result)
        self.assertIn("Resume immediately", result)

    def test_advisory_enforcement_indicator(self):
        """Advisory mode injects enforcement indicator into context."""
        import session_start

        self._write_events([make_event()])
        with _override_settings({"enforcement": "advisory"}):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=self.smm_dir,
            )
            self.assertIn("[enforcement: advisory]", result)

    def test_strict_enforcement_no_label(self):
        """Strict mode has no enforcement label."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("[enforcement:", result)

    def test_writes_needs_session_review_marker(self):
        """session_start writes .needs-session-review marker with source."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-session-review"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "startup")

    def test_resume_does_not_set_marker(self):
        """resume is mid-session — should NOT set .needs-session-review."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-session-review"
        self.assertFalse(marker.exists())

    def test_compact_does_not_set_marker(self):
        """compact is mid-session — should NOT set .needs-session-review."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-session-review"
        self.assertFalse(marker.exists())

    def test_no_smm_in_context(self):
        """session_start should NOT inject SMM content into context."""
        import session_start

        self._write_events([make_event("goal", content="Ship v1")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("<smm-context>", result)
        self.assertNotIn("Project Goals", result)

    def test_no_goal_nudge_in_context(self):
        """Goal nudge removed — handled by /xp-session-review."""
        import session_start

        self._write_events([make_event("status", content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-goal-collection", result)


# ===========================================================================
# retrospective.py tests
# ===========================================================================


class TestRetrospective(_HookTestCase):
    def setUp(self):
        super().setUp()
        # Create retrospectives/ directory
        self.retro_dir = self.smm_dir / "retrospectives"
        self.retro_dir.mkdir()

    def test_xp_agent_skips(self):
        import retrospective

        result = retrospective.run(
            {"session_id": "test", "source": "startup", "agent_type": "xp-retro"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_compact_source_skips(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(10)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_insufficient_events_no_file(self):
        import retrospective

        # Only 3 events — below threshold of 5
        events = [make_event(content=f"event {i}") for i in range(3)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_sufficient_events_writes_file(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())

    def test_retro_input_json_structure(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("unanalyzed_count", data)
        self.assertIn("events_since_last_retro", data)
        self.assertIn("previous_retros", data)
        self.assertIn("event_type_counts", data)
        self.assertEqual(data["unanalyzed_count"], 6)
        self.assertEqual(len(data["events_since_last_retro"]), 6)

    def test_counts_events_after_last_retro(self):
        import retrospective

        # 10 events, retro at position 7, then 2 more — only 2 unanalyzed
        events = [make_event(content=f"event {i}") for i in range(7)]
        events.append(make_event("retrospective", content="retro done"))
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Only 2 events after retro — below threshold
        self.assertIsNone(result)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_retro_history_gathered(self):
        import retrospective

        # Write a previous retro file
        retro_data = {"keep": [{"content": "good TDD"}], "fix": [], "try": []}
        (self.retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["previous_retros"]), 1)
        self.assertEqual(data["previous_retros"][0]["keep"][0]["content"], "good TDD")

    def test_retro_history_limited_to_3(self):
        import retrospective

        # Write 5 retro files
        for i in range(5):
            retro_data = {"keep": [{"content": f"retro {i}"}], "fix": [], "try": []}
            (self.retro_dir / f"2026-03-0{i + 1}T00-00-00.json").write_text(
                json.dumps(retro_data)
            )
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["previous_retros"]), 3)

    def test_retro_history_empty_dir(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["previous_retros"], [])

    def test_graceful_no_smm_dir(self):
        import retrospective

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_context_returned_when_needed(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        # Context should mention the event count
        self.assertIn("6", result)

    def test_event_type_counts(self):
        import retrospective

        events = [
            make_event("decision", content="decided X", topic="arch"),
            make_event("decision", content="decided Y", topic="api"),
            make_event("concern", content="issue A", severity="high"),
            make_event(content="input 1"),
            make_event(content="input 2"),
            make_event(content="input 3"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["event_type_counts"]["decision"], 2)
        self.assertEqual(data["event_type_counts"]["concern"], 1)
        self.assertEqual(data["event_type_counts"]["customer_input"], 3)

    def test_session_stats_key_exists(self):
        import retrospective

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("session_stats", data)

    def test_session_stats_status_count(self):
        import retrospective

        events = [
            make_event("status", content="Working", working_on=["a.py"]),
            make_event("status", content="Working2", working_on=["b.py"]),
            make_event("status", content="Working3", working_on=["c.py"]),
            make_event(content="filler 1"),
            make_event(content="filler 2"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["status_count"], 3)

    def test_session_stats_concerns(self):
        import retrospective

        c1 = make_event("concern", content="Issue A")
        c2 = make_event("concern", content="Issue B")
        resolver = make_event(
            "status",
            content="Fixed",
            working_on=["test.py"],
            metadata={"resolves": [c1["id"]]},
        )
        events = [c1, c2, resolver, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["concerns_raised"], 2)
        self.assertEqual(data["session_stats"]["concerns_resolved"], 1)

    def test_session_stats_questions(self):
        import retrospective

        q1 = make_event("question", content="Q1?", priority="\U0001f534")
        q2 = make_event("question", content="Q2?", priority="\U0001f7e1")
        a = make_event("answer", content="Yes", references=[q1["id"]])
        events = [q1, q2, a, make_event(content="f1"), make_event(content="f2")]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["questions_open"], 1)
        self.assertEqual(data["session_stats"]["questions_answered"], 1)

    def test_session_stats_decisions(self):
        import retrospective

        events = [
            make_event("decision", content="Use Postgres", topic="db"),
            make_event(
                "decision", content="Use REST", topic="api", metadata={"draft": True}
            ),
            make_event(content="f1"),
            make_event(content="f2"),
            make_event(content="f3"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["decisions_total"], 2)
        self.assertEqual(data["session_stats"]["decisions_draft"], 1)


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

    def test_final_status_recorded_true(self):
        import session_end

        s = make_event("status", agent_id="main", working_on=["f.py"])
        self._write_events([s])
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertTrue(se["final_status_recorded"])

    def test_final_status_recorded_false(self):
        import session_end

        self._write_events([make_event()])  # Not a status event from main
        session_end.run(
            {"session_id": "test", "reason": "logout"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertFalse(se["final_status_recorded"])

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


# ===========================================================================
# Plugin config tests
# ===========================================================================


class TestPluginConfig(unittest.TestCase):
    """AC: Plugin loads without errors."""

    def test_plugin_json_valid(self):
        plugin_path = (
            Path(__file__).parent.parent.parent / ".claude-plugin" / "plugin.json"
        )
        with open(plugin_path) as f:
            data = json.load(f)
        self.assertEqual(data["name"], "xp-agents")
        self.assertIn("version", data)
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

    def test_hooks_json_valid(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("hooks", data)
        # All lifecycle + core hooks registered
        self.assertIn("SessionStart", data["hooks"])
        self.assertIn("SessionEnd", data["hooks"])
        self.assertIn("PreCompact", data["hooks"])
        self.assertIn("SubagentStart", data["hooks"])
        self.assertIn("PreToolUse", data["hooks"])
        self.assertIn("PostToolUse", data["hooks"])

    def test_hooks_use_plugin_root_var(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        raw = hooks_path.read_text()
        # All command paths must use ${CLAUDE_PLUGIN_ROOT}
        self.assertNotIn("scripts/", raw.replace("${CLAUDE_PLUGIN_ROOT}/scripts/", ""))

    def test_settings_json_valid(self):
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        with open(settings_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)


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


# ===========================================================================
# M6.5: Retrospective nudge tests
# ===========================================================================


class TestRetrospectiveNudge(_HookTestCase):
    """M6.5: retrospective.py should nudge invoking xp-retrospective."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "retrospectives").mkdir()

    def test_retro_context_has_nudge(self):
        import retrospective

        events = [make_event(content=f"e{i}") for i in range(6)]
        self._write_events(events)
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-retrospective", result)

    def test_retro_below_threshold_no_nudge(self):
        import retrospective

        self._write_events([make_event()])
        result = retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestSessionStartCustomerNudge(_HookTestCase):
    """M6.5: session_start.py should nudge goal-collection / question-triage."""

    def test_no_goal_nudge_removed(self):
        """Goal nudge removed — handled by /xp-session-review."""
        import session_start

        self._write_events([make_event("status", content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-goal-collection", result)

    def test_no_question_nudge_removed(self):
        """Question nudge removed — handled by /xp-session-review."""
        import session_start

        self._write_events(
            [
                make_event("goal", content="Build the app"),
                make_event(
                    "question",
                    content="Which DB?",
                    priority=_common.PRIORITY_BLOCKING,
                ),
            ]
        )
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-question-triage", result)


# ===========================================================================
# session_review_gate.py tests
# ===========================================================================


class TestSessionReviewGate(_HookTestCase):
    """Tests for UserPromptSubmit session review gate."""

    def test_blocks_when_marker_exists(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").touch()
        result = session_review_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")

    def test_allows_session_review_command(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").touch()
        result = session_review_gate.run(
            {"session_id": "test", "prompt": "/xp-session-review"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_passes_when_no_marker(self):
        import session_review_gate

        result = session_review_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").touch()
        result = session_review_gate.run(
            {
                "session_id": "test",
                "prompt": "work",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_advisory_mode_allows(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").touch()
        with _override_settings({"enforcement": "advisory"}):
            result = session_review_gate.run(
                {"session_id": "test", "prompt": "do work"},
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_clear_marker_nudges_instead_of_blocking(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").write_text("clear")
        result = session_review_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, "nudge")

    def test_startup_marker_blocks(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").write_text("startup")
        result = session_review_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["decision"], "block")

    def test_skips_task_notifications(self):
        import session_review_gate

        (self.smm_dir / ".needs-session-review").write_text("startup")
        task_prompt = (
            "<task-notification>\n<task-id>abc</task-id>\n</task-notification>"
        )
        result = session_review_gate.run(
            {"session_id": "test", "prompt": task_prompt},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# session_start behavioral guide tests
# ===========================================================================


class TestSessionStartBehavioralGuide(_HookTestCase):
    """Behavioral guide moved to session_review_done."""

    def test_session_start_no_behavioral_guide(self):
        """session_start should NOT include behavioral guide."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("Honesty Principle", result)

    def test_session_start_includes_skills(self):
        """Output should still contain skill names."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("smm-protocol", result)
        self.assertIn("xp-values", result)

    def test_no_smm_in_session_start(self):
        """SMM is no longer injected by session_start (deferred to session-review)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("<smm-context>", result)


# ===========================================================================
# PostToolUse:Skill — session_review_done.py
# ===========================================================================

import session_review_done  # noqa: E402


class TestSessionReviewDone(_HookTestCase):
    """PostToolUse:Skill hook injects SMM + behavioral guide after session review."""

    def _skill_input(self, skill: str = "xp-housekeeping", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_injects_smm_on_housekeeping(self):
        """Should inject materialized SMM after xp-housekeeping."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("Shared Mental Model", result)

    def test_injects_behavioral_guide(self):
        """Should inject BEHAVIORAL_GUIDE.md after xp-housekeeping."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("XP Agent Behavioral Guide", result)

    def test_ignores_other_skills(self):
        """Should return None for non-housekeeping skills."""
        self._write_events([make_event("goal", content="Ship v1")])
        result = session_review_done.run(
            self._skill_input("simplify"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """Should skip for xp-agent types."""
        result = session_review_done.run(
            self._skill_input(agent_type="xp-test"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)

    def test_smm_before_behavioral_guide(self):
        """SMM appears before behavioral guide in output."""
        self._write_events([make_event("goal", content="Ship v1")])
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n## Intent\n- Ship v1\n"
        )
        result = session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        smm_pos = result.find("Shared Mental Model")
        guide_pos = result.find("XP Agent Behavioral Guide")
        self.assertGreater(guide_pos, smm_pos)

    def test_reads_four_pillar_smm_file(self):
        """When SMM file exists on disk, reads it instead of materializing."""
        four_pillar = (
            "# Shared Mental Model\n\n"
            "## Intent\n- Ship v1\n\n"
            "## Constraints\n- Use Postgres\n\n"
            "## Risks\n- No tests\n\n"
            "## Wisdom\n- Write tests first\n"
        )
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(four_pillar)
        result = session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("## Intent", result)
        self.assertIn("## Constraints", result)
        self.assertIn("## Wisdom", result)

    def test_falls_back_to_empty_without_smm_file(self):
        """When no SMM file exists, returns guide-only (no SMM context tag)."""
        self._write_events([make_event("goal", content="Ship v1")])
        # Ensure no SMM file on disk
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.unlink(missing_ok=True)
        result = session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        if result is not None:
            # Should not contain the SMM context wrapper tag
            self.assertNotIn("<smm-context>", result)

    def test_deletes_needs_session_review_marker(self):
        """Should delete .needs-session-review marker after injection."""
        marker = self.smm_dir / ".needs-session-review"
        marker.touch()
        self._write_events([make_event("goal", content="Ship v1")])
        session_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
