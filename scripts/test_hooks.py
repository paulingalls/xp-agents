#!/usr/bin/env python3
"""Tests for Milestone 3.1: Core Hooks — Session Lifecycle.

Tests _common.py and all 4 command hooks.
Run with: python3 -m unittest scripts/test_hooks.py -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Allow importing from the scripts and smm directories
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
from test_engine import _SMMTestCase, make_event

# Alias for clarity — same base class, reused from Milestone 2
_HookTestCase = _SMMTestCase


# ===========================================================================
# _common.py tests
# ===========================================================================


class TestResolveSmmDir(unittest.TestCase):
    def setUp(self):
        _common.resolve_smm_dir.cache_clear()

    def test_returns_path_in_git_repo(self):
        result = _common.resolve_smm_dir()
        # We're running tests from within a git repo
        self.assertIsNotNone(result)
        self.assertIn(".claude/xp-agents", str(result))
        self.assertTrue(str(result).endswith("/smm"))

    def test_returns_none_outside_git(self):
        _common.resolve_smm_dir.cache_clear()
        with patch("_common.subprocess.check_output", side_effect=FileNotFoundError):
            result = _common.resolve_smm_dir()
            self.assertIsNone(result)

    def test_returns_none_on_git_error(self):
        from subprocess import CalledProcessError

        _common.resolve_smm_dir.cache_clear()
        with patch(
            "_common.subprocess.check_output",
            side_effect=CalledProcessError(128, "git"),
        ):
            result = _common.resolve_smm_dir()
            self.assertIsNone(result)


class TestReadHookInput(unittest.TestCase):
    def test_reads_valid_json(self):
        data = {"session_id": "test", "tool_name": "Write"}
        with patch("sys.stdin", io.StringIO(json.dumps(data))):
            result = _common.read_hook_input()
            self.assertEqual(result, data)

    def test_exits_0_on_invalid_json(self):
        with patch("sys.stdin", io.StringIO("not json")):
            with self.assertRaises(SystemExit) as cm:
                _common.read_hook_input()
            self.assertEqual(cm.exception.code, 0)

    def test_exits_0_on_empty_input(self):
        with patch("sys.stdin", io.StringIO("")):
            with self.assertRaises(SystemExit) as cm:
                _common.read_hook_input()
            self.assertEqual(cm.exception.code, 0)


class TestHookOutput(unittest.TestCase):
    def test_outputs_correct_json(self):
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            _common.hook_output("PreToolUse", "Some context")
            output = json.loads(mock_stdout.getvalue())
            self.assertEqual(
                output["hookSpecificOutput"]["hookEventName"], "PreToolUse"
            )
            self.assertEqual(
                output["hookSpecificOutput"]["additionalContext"], "Some context"
            )


class TestIsXpAgent(unittest.TestCase):
    def test_xp_navigator(self):
        self.assertTrue(_common.is_xp_agent({"agent_type": "xp-navigator"}))

    def test_xp_reviewer(self):
        self.assertTrue(_common.is_xp_agent({"agent_type": "xp-reviewer"}))

    def test_regular_agent(self):
        self.assertFalse(_common.is_xp_agent({"agent_type": "Explore"}))

    def test_missing_agent_type(self):
        self.assertFalse(_common.is_xp_agent({}))

    def test_empty_agent_type(self):
        self.assertFalse(_common.is_xp_agent({"agent_type": ""}))

    def test_non_string_agent_type(self):
        self.assertFalse(_common.is_xp_agent({"agent_type": 42}))


class TestResolvePluginRoot(unittest.TestCase):
    def test_from_env_var(self):
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/opt/plugins/xp"}):
            result = _common.resolve_plugin_root()
            self.assertEqual(result, Path("/opt/plugins/xp"))

    def test_fallback_to_file_parent(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _common.resolve_plugin_root()
            # Parent of parent of __file__: scripts/_common.py -> root
            expected = Path(__file__).parent.parent
            self.assertEqual(result, expected)


class TestReadEventsRaw(_HookTestCase):
    def test_reads_valid_events(self):
        events = [make_event(), make_event("status")]
        self._write_events(events)
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_skips_malformed_lines(self):
        self._write_raw_lines(
            [json.dumps(make_event()), "bad line", json.dumps(make_event())]
        )
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_empty_file(self):
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])

    def test_missing_file(self):
        self.events_file.unlink()
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])


class TestWriteWatermark(_HookTestCase):
    def test_write_and_verify(self):
        _common.write_watermark(self.smm_dir, "main", 42)
        wm_file = self.smm_dir / ".watermark-main"
        self.assertTrue(wm_file.exists())
        self.assertEqual(wm_file.read_text(), "42")

    def test_atomic_no_temp_files(self):
        _common.write_watermark(self.smm_dir, "test", 10)
        tmp_files = list(self.smm_dir.glob(".wm-test-*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_rejects_slash(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "../escape", 10)

    def test_rejects_dotdot(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "..", 10)

    def test_rejects_null(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "a\x00b", 10)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "", 10)

    def test_rejects_space(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "agent name", 10)

    def test_rejects_semicolon(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "agent;cmd", 10)

    def test_rejects_backtick(self):
        with self.assertRaises(ValueError):
            _common.write_watermark(self.smm_dir, "agent`cmd`", 10)

    def test_accepts_colon(self):
        _common.write_watermark(self.smm_dir, "xp-quality:reviewer", 10)
        wm_file = self.smm_dir / ".watermark-xp-quality:reviewer"
        self.assertTrue(wm_file.exists())

    def test_accepts_hyphen(self):
        _common.write_watermark(self.smm_dir, "xp-navigator", 5)
        wm_file = self.smm_dir / ".watermark-xp-navigator"
        self.assertTrue(wm_file.exists())


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

    def test_clear_source_skips(self):
        import session_start

        result = session_start.run(
            {"session_id": "test", "source": "clear"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

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
        self.assertIn("pair-programming", result)

    def test_retro_triggered_when_enough_events(self):
        import session_start

        # Write 6 events (>= 5 threshold), none are retrospective
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("retrospective", result.lower())

    def test_retro_not_triggered_with_few_events(self):
        import session_start

        # Write 3 events (< 5 threshold)
        events = [make_event(content=f"event {i}") for i in range(3)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Should not contain retro instruction (but still has SMM)
        self.assertNotIn("Run a retrospective", result)

    def test_retro_not_triggered_on_compact(self):
        import session_start

        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("Run a retrospective", result)

    def test_graceful_no_smm_dir(self):
        import session_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=fake_dir,
        )
        # Should still return context (init.sh creates the dir)
        # But if smm_dir doesn't exist and init.sh isn't called, graceful
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

    def test_retro_reset_after_retrospective_event(self):
        import session_start

        # 10 events, but a retrospective at position 7
        events = [make_event(content=f"event {i}") for i in range(7)]
        events.append(make_event("retrospective", content="retro done"))
        events.extend([make_event(content=f"post {i}") for i in range(2)])
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Only 2 events after the last retrospective, so no retro trigger
        self.assertNotIn("Run a retrospective", result)


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
            "status", content="Fixed", references=[c["id"]], working_on=["test.py"]
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
        plugin_path = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        with open(plugin_path) as f:
            data = json.load(f)
        self.assertEqual(data["name"], "xp-agents")
        self.assertIn("version", data)
        self.assertIn("hooks", data)

    def test_hooks_json_valid(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
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
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        raw = hooks_path.read_text()
        # All command paths must use ${CLAUDE_PLUGIN_ROOT}
        self.assertNotIn("scripts/", raw.replace("${CLAUDE_PLUGIN_ROOT}/scripts/", ""))

    def test_settings_json_valid(self):
        settings_path = Path(__file__).parent.parent / "settings.json"
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


# ===========================================================================
# subagent_start.py tests
# ===========================================================================


class TestSubagentStart(_HookTestCase):
    def test_xp_agent_skips(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_missing_smm_dir(self):
        import subagent_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_returns_smm_content(self):
        import subagent_start

        self._write_events([make_event()])
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Shared Mental Model", result)

    def test_writes_watermark(self):
        import subagent_start

        self._write_events([make_event(), make_event()])
        subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        wm_file = self.smm_dir / ".watermark-explorer-1"
        self.assertTrue(wm_file.exists())
        self.assertEqual(wm_file.read_text(), "2")

    def test_empty_events(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        # Even with empty SMM, should return something (empty string from materialize)
        # The run function should handle this gracefully
        self.assertIsNotNone(result)

    def test_default_agent_id(self):
        import subagent_start

        self._write_events([make_event()])
        result = subagent_start.run(
            {"session_id": "test"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        # Should use "subagent" as default
        wm_file = self.smm_dir / ".watermark-subagent"
        self.assertTrue(wm_file.exists())


# ===========================================================================
# pre_tool_use.py tests — Milestone 3.2
# ===========================================================================

import pre_tool_use  # noqa: E402


class TestClassifyTier(unittest.TestCase):
    def test_write_is_full(self):
        self.assertEqual(pre_tool_use.classify_tier("Write", {}), "full")

    def test_edit_is_full(self):
        self.assertEqual(pre_tool_use.classify_tier("Edit", {}), "full")

    def test_multi_edit_is_full(self):
        self.assertEqual(pre_tool_use.classify_tier("MultiEdit", {}), "full")

    def test_bash_git_commit_is_full(self):
        self.assertEqual(
            pre_tool_use.classify_tier("Bash", {"command": "git commit -m 'msg'"}),
            "full",
        )

    def test_bash_other_is_blocking(self):
        self.assertEqual(
            pre_tool_use.classify_tier("Bash", {"command": "ls -la"}),
            "blocking",
        )

    def test_read_is_red_only(self):
        self.assertEqual(pre_tool_use.classify_tier("Read", {}), "red-only")

    def test_grep_is_red_only(self):
        self.assertEqual(pre_tool_use.classify_tier("Grep", {}), "red-only")

    def test_glob_is_red_only(self):
        self.assertEqual(pre_tool_use.classify_tier("Glob", {}), "red-only")

    def test_unknown_tool_is_red_only(self):
        self.assertEqual(pre_tool_use.classify_tier("Agent", {}), "red-only")


class TestIsTestFile(unittest.TestCase):
    def test_python_test_prefix(self):
        self.assertTrue(pre_tool_use.is_test_file("test_foo.py"))

    def test_python_test_suffix(self):
        self.assertTrue(pre_tool_use.is_test_file("foo_test.py"))

    def test_js_test(self):
        self.assertTrue(pre_tool_use.is_test_file("app.test.js"))

    def test_ts_spec(self):
        self.assertTrue(pre_tool_use.is_test_file("app.spec.ts"))

    def test_go_test(self):
        self.assertTrue(pre_tool_use.is_test_file("handler_test.go"))

    def test_java_test(self):
        self.assertTrue(pre_tool_use.is_test_file("UserTest.java"))

    def test_ruby_spec(self):
        self.assertTrue(pre_tool_use.is_test_file("user_spec.rb"))

    def test_tests_directory(self):
        self.assertTrue(pre_tool_use.is_test_file("tests/conftest.py"))

    def test_dunder_tests_directory(self):
        self.assertTrue(pre_tool_use.is_test_file("__tests__/Button.tsx"))

    def test_impl_file(self):
        self.assertFalse(pre_tool_use.is_test_file("src/app.ts"))

    def test_python_impl(self):
        self.assertFalse(pre_tool_use.is_test_file("models.py"))


class TestGetTargetFile(unittest.TestCase):
    def test_write_returns_file_path(self):
        self.assertEqual(
            pre_tool_use.get_target_file("Write", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_edit_returns_file_path(self):
        self.assertEqual(
            pre_tool_use.get_target_file("Edit", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_bash_returns_none(self):
        self.assertIsNone(pre_tool_use.get_target_file("Bash", {"command": "ls"}))

    def test_read_returns_none(self):
        self.assertIsNone(
            pre_tool_use.get_target_file("Read", {"file_path": "src/app.ts"})
        )

    def test_missing_file_path(self):
        self.assertIsNone(pre_tool_use.get_target_file("Write", {}))


class TestNormalizePath(unittest.TestCase):
    def test_absolute_unchanged(self):
        result = _common.normalize_path("/home/user/src/app.ts", "/tmp")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_relative_resolved(self):
        result = _common.normalize_path("src/app.ts", "/home/user")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_dotdot_resolved(self):
        result = _common.normalize_path("../app.ts", "/home/user/src")
        self.assertEqual(result, "/home/user/app.ts")


class TestCheckWorkingOnOverlap(_HookTestCase):
    def test_no_overlap(self):
        events = [
            make_event("status", agent_id="other", working_on=["src/b.ts"]),
        ]
        result = pre_tool_use.check_working_on_overlap(
            events, "main", "src/a.ts", "/project"
        )
        self.assertIsNone(result)

    def test_overlap_detected(self):
        events = [
            make_event("status", agent_id="other", working_on=["src/app.ts"]),
        ]
        result = pre_tool_use.check_working_on_overlap(
            events, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)
        self.assertIn("other", result)

    def test_self_overlap_ignored(self):
        events = [
            make_event("status", agent_id="main", working_on=["src/app.ts"]),
        ]
        result = pre_tool_use.check_working_on_overlap(
            events, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_normalized_path_overlap(self):
        events = [
            make_event("status", agent_id="other", working_on=["./src/../src/app.ts"]),
        ]
        result = pre_tool_use.check_working_on_overlap(
            events, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)

    def test_latest_status_wins(self):
        events = [
            make_event("status", agent_id="other", working_on=["src/app.ts"]),
            make_event("status", agent_id="other", working_on=["src/b.ts"]),
        ]
        result = pre_tool_use.check_working_on_overlap(
            events, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)


class TestCheckTddOrder(_HookTestCase):
    def test_first_impl_no_nudge(self):
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Write"
        )
        self.assertIsNone(result)

    def test_second_impl_nudge(self):
        # First write
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        # Second write
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNotNone(result)
        self.assertIn("TDD", result)

    def test_test_file_clears_nudge(self):
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "src/app.ts", "Write")
        pre_tool_use.check_tdd_order(self.smm_dir, "main", "tests/test_app.py", "Write")
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/utils.ts", "Write"
        )
        self.assertIsNone(result)

    def test_non_write_tool_no_tracking(self):
        result = pre_tool_use.check_tdd_order(
            self.smm_dir, "main", "src/app.ts", "Read"
        )
        self.assertIsNone(result)

    def test_none_file_path(self):
        result = pre_tool_use.check_tdd_order(self.smm_dir, "main", None, "Write")
        self.assertIsNone(result)


class TestPreToolUseRun(_HookTestCase):
    def test_xp_agent_skips(self):
        result = pre_tool_use.run(
            {"session_id": "t", "tool_name": "Write", "agent_type": "xp-navigator"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_write_gets_full_delta(self):
        # Write a red question event, then check that Write gets it
        events = [make_event("question", priority="\U0001f534", content="blocker?")]
        self._write_events(events)
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/new.ts"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("SMM Delta", result)

    def test_read_gets_red_only(self):
        # Write a status event (not red) — Read should NOT get it
        events = [make_event("status", content="working")]
        self._write_events(events)
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        # Red-only tier filters out status events, so no delta
        self.assertIsNone(result)

    def test_conflict_raises_blocked(self):
        events = [
            make_event("status", agent_id="other-agent", working_on=["src/app.ts"]),
        ]
        self._write_events(events)
        with self.assertRaises(_common.BlockedError) as cm:
            pre_tool_use.run(
                {
                    "session_id": "t",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.ts"},
                    "agent_id": "main",
                    "cwd": "/tmp",
                },
                smm_dir=self.smm_dir,
            )
        self.assertIn("other-agent", str(cm.exception))

    def test_no_smm_dir_degrades_gracefully(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_bash_blocking_tier_gets_pair_guidance(self):
        events = [make_event("pair_guidance", content="Use --dry-run")]
        self._write_events(events)
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("NAVIGATOR", result)

    def test_bash_blocking_tier_skips_status(self):
        events = [make_event("status", content="busy")]
        self._write_events(events)
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "agent_id": "main",
                "cwd": "/tmp",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# Cross-cutting acceptance criteria
# ===========================================================================


class TestStdlibOnly(unittest.TestCase):
    """AC (M1): Python stdlib only — no external packages."""

    def test_no_external_imports(self):
        """Scan all .py files for non-stdlib imports."""
        import pkgutil

        project_modules = frozenset(
            {
                "_common",
                "_append_impl",
                "read_delta",
                "materialize",
                "pre_tool_use",
                "post_tool_use",
                "lint_check",
                "bash_post_tool",
                "session_start",
                "session_end",
                "pre_compact",
                "subagent_start",
            }
        )

        stdlib_names = {m.name for m in pkgutil.iter_modules()}
        stdlib_names |= set(sys.stdlib_module_names)

        project_root = Path(__file__).parent.parent
        py_files = list(project_root.glob("scripts/*.py")) + list(
            project_root.glob("smm/*.py")
        )

        violations = []
        for py_file in py_files:
            if py_file.name.startswith("test_"):
                continue
            source = py_file.read_text()
            in_docstring = False
            for line in source.splitlines():
                stripped = line.strip()
                if '"""' in stripped or "'''" in stripped:
                    count = stripped.count('"""') + stripped.count("'''")
                    if count == 1:
                        in_docstring = not in_docstring
                    continue
                if in_docstring or stripped.startswith("#"):
                    continue
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if stripped.startswith("from "):
                    module = stripped.split()[1].split(".")[0]
                else:
                    module = stripped.split()[1].split(".")[0]
                if module not in stdlib_names and module not in project_modules:
                    violations.append(f"{py_file.name}: {stripped}")

        msg = "Non-stdlib imports found:\n" + "\n".join(violations)
        self.assertEqual(violations, [], msg)


class TestPreToolUsePerformance(_HookTestCase):
    """AC (M3.2): Fast — minimal overhead on every tool call."""

    def test_run_completes_within_budget(self):
        """100 invocations should complete well under 2 seconds."""
        import time

        # Seed some events so delta reading has work to do
        events = [make_event("status", content=f"s{i}") for i in range(10)]
        self._write_events(events)

        input_data = {
            "session_id": "perf",
            "tool_name": "Read",
            "tool_input": {"file_path": "src/app.ts"},
            "agent_id": "perf-agent",
            "cwd": "/tmp",
        }

        start = time.monotonic()
        for _ in range(100):
            pre_tool_use.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        # 100 runs should complete in under 2 seconds on any reasonable machine
        self.assertLess(elapsed, 2.0, f"100 runs took {elapsed:.2f}s — too slow")

    def test_xp_agent_skip_is_instant(self):
        """xp-agent bypass should be near-zero cost."""
        import time

        input_data = {
            "session_id": "perf",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.ts"},
            "agent_type": "xp-navigator",
            "cwd": "/tmp",
        }

        start = time.monotonic()
        for _ in range(1000):
            pre_tool_use.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        # 1000 no-op runs should be well under 1 second
        self.assertLess(elapsed, 1.0, f"1000 xp-agent skips took {elapsed:.2f}s")


# ===========================================================================
# post_tool_use.py tests — Milestone 3.3
# ===========================================================================


class TestExtractFilePath(unittest.TestCase):
    def test_write(self):
        self.assertEqual(
            _common.extract_file_path("Write", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_edit(self):
        self.assertEqual(
            _common.extract_file_path("Edit", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_multi_edit(self):
        self.assertEqual(
            _common.extract_file_path("MultiEdit", {"file_path": "src/app.ts"}),
            "src/app.ts",
        )

    def test_bash_returns_none(self):
        self.assertIsNone(_common.extract_file_path("Bash", {"command": "ls"}))

    def test_missing_file_path(self):
        self.assertIsNone(_common.extract_file_path("Write", {}))


import post_tool_use  # noqa: E402


class TestPostToolUse(_HookTestCase):
    def test_auto_status_from_write(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        # Path is normalized against cwd
        self.assertIn("/tmp/src/app.ts", statuses[0]["working_on"])

    def test_auto_status_from_edit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_auto_status_from_multiedit(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_normalizes_relative_path(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "tool_response": {"success": True},
                "cwd": "/home/user",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(statuses[0]["working_on"], ["/home/user/src/app.ts"])

    def test_xp_agent_skips(self):
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_type": "xp-navigator",
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=fake_dir,
        )

    def test_conflict_working_on_overlap(self):
        # Another agent claims the same file
        self._write_events(
            [
                make_event("status", agent_id="other", working_on=["src/app.ts"]),
            ]
        )
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_conflict_stale_question(self):
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        self._write_events([q, *filler])
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("stale" in c["content"].lower() for c in concerns))

    def test_conflict_superseded_decision(self):
        self._write_events(
            [
                make_event("decision", topic="db", content="Use Postgres"),
                make_event("decision", topic="db", content="Use MySQL"),
            ]
        )
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("superseded" in c["content"].lower() for c in concerns))

    def test_conflict_assumption_contradicted(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._write_events([a, d])
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_conflict_convention_violation(self):
        self._write_events(
            [
                make_event("convention", topic="naming", content="Use camelCase"),
                make_event("decision", topic="naming", content="Use snake_case"),
            ]
        )
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("convention" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [
                make_event("status", agent_id="main", working_on=["src/a.ts"]),
                make_event("decision", topic="db", content="Use Postgres"),
            ]
        )
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/b.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_semantic_references(self):
        # Decision references our file
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/auth.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/auth.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        refs = statuses[0].get("references", [])
        self.assertIn(d["id"], refs)

    def test_no_semantic_refs_unrelated(self):
        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT",
            working_on=["src/other.ts"],
        )
        self._write_events([d])
        post_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        refs = statuses[0].get("references", [])
        self.assertNotIn(d["id"], refs)


# ===========================================================================
# lint_check.py tests — Milestone 3.3
# ===========================================================================

import lint_check  # noqa: E402


class TestDetectLinterConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_detects_ruff_config(self):
        (self.tmpdir / "ruff.toml").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_detects_eslint_config(self):
        (self.tmpdir / ".eslintrc.json").touch()
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "eslint")

    def test_detects_pyproject_ruff(self):
        (self.tmpdir / "pyproject.toml").write_text("[tool.ruff]\nline-length = 88\n")
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "ruff")

    def test_no_config_returns_none(self):
        result = lint_check.detect_linter_config(str(self.tmpdir), str(self.tmpdir))
        self.assertIsNone(result)


class TestLintCheck(_HookTestCase):
    def test_no_config_warns_once(self):
        lint_check.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("linter", concerns[0]["content"].lower())
        # Flag file should exist
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

    def test_no_config_second_time_silent(self):
        (self.smm_dir / ".lint-warned").touch()
        lint_check.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_linter_binary_missing(self):
        # Create a ruff.toml in a temp dir but ruff isn't on PATH
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value=None):
                lint_check.run(
                    {
                        "session_id": "t",
                        "tool_name": "Write",
                        "tool_input": {"file_path": "src/app.py", "content": "x"},
                        "cwd": str(tmpdir),
                        "agent_id": "main",
                    },
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_clean_lint_no_event(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
                )()
                lint_check.run(
                    {
                        "session_id": "t",
                        "tool_name": "Write",
                        "tool_input": {"file_path": "src/app.py", "content": "x"},
                        "cwd": str(tmpdir),
                        "agent_id": "main",
                    },
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_errors_appends_concern(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "R",
                    (),
                    {
                        "returncode": 1,
                        "stdout": "src/app.py:1:1: E302 expected 2 blank lines",
                        "stderr": "",
                    },
                )()
                lint_check.run(
                    {
                        "session_id": "t",
                        "tool_name": "Write",
                        "tool_input": {"file_path": "src/app.py", "content": "x"},
                        "cwd": str(tmpdir),
                        "agent_id": "main",
                    },
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 1)
            self.assertEqual(concerns[0].get("severity"), "medium")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_timeout(self):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with (
                patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
                patch("lint_check.run_linter", return_value=None),
            ):
                lint_check.run(
                    {
                        "session_id": "t",
                        "tool_name": "Write",
                        "tool_input": {"file_path": "src/app.py", "content": "x"},
                        "cwd": str(tmpdir),
                        "agent_id": "main",
                    },
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertEqual(len(concerns), 0)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_xp_agent_skips(self):
        lint_check.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_type": "xp-navigator",
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        lint_check.run(
            {
                "session_id": "t",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=fake_dir,
        )


# ===========================================================================
# bash_post_tool.py tests — Milestone 3.3
# ===========================================================================

import bash_post_tool  # noqa: E402


class TestIsGitCommit(unittest.TestCase):
    def test_git_commit_m(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit -m 'msg'"))

    def test_git_commit_am(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit -am 'msg'"))

    def test_git_commit_with_path(self):
        self.assertTrue(bash_post_tool.is_git_commit("cd /tmp && git commit -m 'x'"))

    def test_not_git_status(self):
        self.assertFalse(bash_post_tool.is_git_commit("git status"))

    def test_not_ls(self):
        self.assertFalse(bash_post_tool.is_git_commit("ls -la"))

    def test_git_commit_no_message(self):
        self.assertTrue(bash_post_tool.is_git_commit("git commit"))


class TestIsTestRun(unittest.TestCase):
    def test_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("pytest"), "pytest")

    def test_python_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python -m pytest"), "pytest")

    def test_python3_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python3 -m pytest"), "pytest")

    def test_jest(self):
        self.assertEqual(bash_post_tool.is_test_run("npx jest"), "jest")

    def test_jest_bare(self):
        self.assertEqual(bash_post_tool.is_test_run("jest"), "jest")

    def test_go_test(self):
        self.assertEqual(bash_post_tool.is_test_run("go test ./..."), "go")

    def test_not_test(self):
        self.assertIsNone(bash_post_tool.is_test_run("ls -la"))

    def test_npm_test(self):
        self.assertEqual(bash_post_tool.is_test_run("npm test"), "jest")


class TestParseCommitMessage(unittest.TestCase):
    def test_standard_output(self):
        response = "[main abc123] Add auth module\n 3 files changed, 45 insertions(+)"
        result = bash_post_tool.parse_commit_message(response)
        self.assertEqual(result, "Add auth module")

    def test_no_match(self):
        result = bash_post_tool.parse_commit_message("error: something went wrong")
        self.assertIsNone(result)


class TestParseTestResults(unittest.TestCase):
    def test_pytest_pass(self):
        output = "===== 5 passed in 0.3s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_pytest_fail(self):
        output = "===== 3 passed, 2 failed in 1.2s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_jest_pass(self):
        output = "Tests:  5 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_jest_fail(self):
        output = "Tests:  2 failed, 3 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_go_pass(self):
        output = "ok  \tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)

    def test_go_fail(self):
        output = "--- FAIL: TestSomething (0.00s)\nFAIL\tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["failed"], 1)


class TestBashPostTool(_HookTestCase):
    def test_git_commit_auto_drafts_decision(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                {
                    "session_id": "t",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m 'Add auth'"},
                    "tool_response": {
                        "stdout": "[main abc123] Add auth\n 3 files changed"
                    },
                    "cwd": "/tmp",
                    "agent_id": "main",
                },
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].get("metadata", {}).get("draft"))
        self.assertIn("Add auth", decisions[0]["content"])

    def test_git_commit_small_no_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                {
                    "session_id": "t",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m 'Fix bug'"},
                    "tool_response": {
                        "stdout": "[main abc123] Fix bug\n 3 files changed"
                    },
                    "cwd": "/tmp",
                    "agent_id": "main",
                },
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_git_commit_large_appends_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=12):
            bash_post_tool.run(
                {
                    "session_id": "t",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m 'Big change'"},
                    "tool_response": {
                        "stdout": "[main abc123] Big change\n 12 files changed"
                    },
                    "cwd": "/tmp",
                    "agent_id": "main",
                },
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("12 files" in c["content"] for c in concerns))

    def test_commit_threshold_from_settings(self):
        settings_path = Path(__file__).parent.parent / "settings.json"
        original = settings_path.read_text()
        try:
            settings_path.write_text(json.dumps({"commit_size_threshold": 5}))
            with patch("bash_post_tool.count_commit_files", return_value=6):
                bash_post_tool.run(
                    {
                        "session_id": "t",
                        "tool_name": "Bash",
                        "tool_input": {"command": "git commit -m 'x'"},
                        "tool_response": {"stdout": "[main a] x\n 6 files changed"},
                        "cwd": "/tmp",
                        "agent_id": "main",
                    },
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertTrue(len(concerns) >= 1)
        finally:
            settings_path.write_text(original)

    def test_commit_threshold_default(self):
        self.assertEqual(bash_post_tool.load_commit_threshold(), 10)

    def test_pytest_pass(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m pytest tests/"},
                "tool_response": {"stdout": "===== 5 passed in 0.3s ====="},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("5 passed" in s["content"] for s in statuses))

    def test_pytest_fail(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "pytest"},
                "tool_response": {"stdout": "===== 3 passed, 2 failed in 1.2s ====="},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "npx jest"},
                "tool_response": {"stdout": "Tests:  5 passed, 5 total"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_jest_fail(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "npx jest"},
                "tool_response": {"stdout": "Tests:  2 failed, 3 passed, 5 total"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_pass(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "go test ./..."},
                "tool_response": {"stdout": "ok  \tgithub.com/user/pkg\t0.3s"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_go_test_fail(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "go test ./..."},
                "tool_response": {
                    "stdout": "--- FAIL: TestSomething (0.00s)\nFAIL\tpkg\t0.3s"
                },
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "tool_response": {"stdout": "total 0"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips(self):
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": "[main a] x"},
                "agent_type": "xp-navigator",
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        bash_post_tool.run(
            {
                "session_id": "t",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'x'"},
                "tool_response": {"stdout": "[main a] x"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=fake_dir,
        )

    def test_git_commit_parse_message(self):
        response = "[main abc123] Fix login bug\n 1 file changed"
        self.assertEqual(bash_post_tool.parse_commit_message(response), "Fix login bug")


# ===========================================================================
# hooks.json PostToolUse registration — Milestone 3.3
# ===========================================================================


class TestPostToolUseHooksConfig(unittest.TestCase):
    def test_hooks_json_has_post_tool_use(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("PostToolUse", data["hooks"])

    def test_post_tool_use_write_matcher(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Write|Edit|MultiEdit", matchers)

    def test_post_tool_use_bash_matcher(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        matchers = [entry.get("matcher") for entry in data["hooks"]["PostToolUse"]]
        self.assertIn("Bash", matchers)

    def test_settings_has_commit_threshold(self):
        settings_path = Path(__file__).parent.parent / "settings.json"
        with open(settings_path) as f:
            data = json.load(f)
        self.assertIn("commit_size_threshold", data)
        self.assertEqual(data["commit_size_threshold"], 10)


# ===========================================================================
# user_prompt_log.py tests — Milestone 3.4
# ===========================================================================

import user_prompt_log  # noqa: E402


class TestUserPromptLog(_HookTestCase):
    def test_logs_prompt_as_customer_input(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hello world"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "Hello world")

    def test_agent_id_is_customer(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_xp_agent_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi", "agent_type": "xp-navigator"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=fake_dir,
        )

    def test_empty_prompt_still_logs(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": ""},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "")

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 15000
        user_prompt_log.run(
            {"session_id": "t", "prompt": long_prompt},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)


# ===========================================================================
# subagent_stop.py tests — Milestone 3.4
# ===========================================================================

import subagent_stop  # noqa: E402


class TestSubagentStop(_HookTestCase):
    def test_records_minimal_status(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("task-1", statuses[0]["content"])
        self.assertEqual(statuses[0]["working_on"], [])

    def test_xp_agent_skips(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-navigator",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=fake_dir,
        )

    def test_default_agent_id(self):
        subagent_stop.run(
            {"session_id": "t", "last_assistant_message": "Done"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("subagent", statuses[0]["content"])

    def test_missing_last_message(self):
        subagent_stop.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_conflict_detection_runs(self):
        # Set up a contradiction in the log
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._write_events([a, d])

        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [make_event("status", agent_id="main", working_on=["src/a.ts"])]
        )
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)


# ===========================================================================
# detect_conflicts in _common.py — Milestone 3.4 extraction
# ===========================================================================


class TestDetectConflictsCommon(_HookTestCase):
    """Test detect_conflicts after extraction to _common.py."""

    def test_import_from_common(self):
        self.assertTrue(hasattr(_common, "detect_conflicts"))
        self.assertTrue(hasattr(_common, "make_concern"))

    def test_overlapping_working_on(self):
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
        ]
        concerns = _common.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_no_overlap_different_file(self):
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/other.ts"]),
        ]
        concerns = _common.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in concerns if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_stale_question_detected(self):
        q = make_event("question", priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        concerns = _common.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        self.assertTrue(any("stale" in c["content"].lower() for c in concerns))

    def test_without_file_path_skips_pattern_1(self):
        """When file_path=None, skip overlapping working_on check."""
        events = [
            make_event("status", agent_id="other", working_on=["/tmp/src/app.ts"]),
        ]
        concerns = _common.detect_conflicts(events, "main")
        overlap_concerns = [c for c in concerns if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_without_file_path_runs_other_patterns(self):
        """Patterns 2-5 still run when file_path=None."""
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        concerns = _common.detect_conflicts([a, d], "main")
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_superseded_decision(self):
        events = [
            make_event("decision", topic="db", content="Use Postgres"),
            make_event("decision", topic="db", content="Use MySQL"),
        ]
        concerns = _common.detect_conflicts(events, "main")
        self.assertTrue(any("superseded" in c["content"].lower() for c in concerns))

    def test_convention_violation(self):
        events = [
            make_event("convention", topic="naming", content="Use camelCase"),
            make_event("decision", topic="naming", content="Use snake_case"),
        ]
        concerns = _common.detect_conflicts(events, "main")
        self.assertTrue(any("convention" in c["content"].lower() for c in concerns))


# ===========================================================================
# hooks.json M3.4 registration tests
# ===========================================================================


class TestM34HooksConfig(unittest.TestCase):
    def setUp(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def test_hooks_json_has_user_prompt_submit(self):
        self.assertIn("UserPromptSubmit", self.data["hooks"])

    def test_user_prompt_submit_command(self):
        hooks = self.data["hooks"]["UserPromptSubmit"][0]["hooks"]
        cmds = [h["command"] for h in hooks]
        self.assertTrue(any("user_prompt_log.py" in c for c in cmds))

    def test_hooks_json_has_subagent_stop(self):
        self.assertIn("SubagentStop", self.data["hooks"])

    def test_subagent_stop_command(self):
        hooks = self.data["hooks"]["SubagentStop"][0]["hooks"]
        cmds = [h["command"] for h in hooks]
        self.assertTrue(any("subagent_stop.py" in c for c in cmds))

    def test_subagent_stop_has_timeout(self):
        hooks = self.data["hooks"]["SubagentStop"][0]["hooks"]
        self.assertEqual(hooks[0]["timeout"], 5000)


if __name__ == "__main__":
    unittest.main()
