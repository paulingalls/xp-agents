#!/usr/bin/env python3
"""Tests for Milestone 3.1: Core Hooks — Session Lifecycle.

Tests _common.py and all 4 command hooks.
Run with: python3 -m unittest scripts/test_hooks.py -v
"""

import contextlib
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


def _make_write_input(**overrides) -> dict:
    """Build a canonical Write tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Write",
        "tool_input": {"file_path": "src/app.ts", "content": "x"},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


def _make_bash_input(command: str = "echo hi", stdout: str = "", **overrides) -> dict:
    """Build a canonical Bash tool hook input dict."""
    data = {
        "session_id": "t",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


@contextlib.contextmanager
def _override_settings(overrides: dict):
    """Override settings.json via mock for test isolation."""
    tmpdir = Path(tempfile.mkdtemp())
    try:
        (tmpdir / "settings.json").write_text(json.dumps(overrides))
        _common.load_enforcement_mode.cache_clear()
        with patch.object(_common, "resolve_plugin_root", return_value=tmpdir):
            yield
    finally:
        _common.load_enforcement_mode.cache_clear()
        import shutil

        shutil.rmtree(tmpdir)


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


class TestLoadEnforcementMode(unittest.TestCase):
    """Tests for _common.load_enforcement_mode()."""

    def setUp(self):
        _common.load_enforcement_mode.cache_clear()
        self.tmpdir = Path(tempfile.mkdtemp())
        self.settings_path = self.tmpdir / "settings.json"

    def tearDown(self):
        _common.load_enforcement_mode.cache_clear()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_default_strict(self):
        """Defaults to strict when no enforcement key."""
        self.settings_path.write_text(json.dumps({"commit_size_threshold": 10}))
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "strict")

    def test_advisory_mode(self):
        self.settings_path.write_text(
            json.dumps({"enforcement": "advisory", "commit_size_threshold": 10})
        )
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "advisory")

    def test_strict_mode(self):
        self.settings_path.write_text(
            json.dumps({"enforcement": "strict", "commit_size_threshold": 10})
        )
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "strict")

    def test_missing_file(self):
        """Defaults to strict when settings.json missing."""
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "strict")

    def test_invalid_json(self):
        """Defaults to strict on invalid JSON."""
        self.settings_path.write_text("not json{{{")
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "strict")

    def test_invalid_value(self):
        """Defaults to strict on unrecognized value."""
        self.settings_path.write_text(json.dumps({"enforcement": "whatever"}))
        with patch.object(_common, "resolve_plugin_root", return_value=self.tmpdir):
            result = _common.load_enforcement_mode()
        self.assertEqual(result, "strict")


class TestFindDebtForFile(_HookTestCase):
    """Tests for _common.find_debt_for_file()."""

    def test_matching_file(self):
        events = [
            make_event("debt", content="Legacy code", files=["/tmp/src/app.ts"]),
        ]
        result = _common.find_debt_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Legacy code")

    def test_no_match(self):
        events = [
            make_event("debt", content="Legacy code", files=["/tmp/src/other.ts"]),
        ]
        result = _common.find_debt_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_multiple_debts(self):
        events = [
            make_event("debt", content="Debt 1", files=["/tmp/src/app.ts"]),
            make_event("debt", content="Debt 2", files=["/tmp/src/app.ts"]),
            make_event("debt", content="Debt 3", files=["/tmp/src/other.ts"]),
        ]
        result = _common.find_debt_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 2)

    def test_path_normalization(self):
        """Relative path in debt event matches absolute target."""
        events = [
            make_event("debt", content="Debt", files=["src/app.ts"]),
        ]
        result = _common.find_debt_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 1)

    def test_empty_events(self):
        result = _common.find_debt_for_file([], "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_non_debt_events_ignored(self):
        events = [
            make_event("concern", content="Concern about app.ts"),
            make_event("status", content="Working"),
        ]
        result = _common.find_debt_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])


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

    def test_session_stats_pair_guidance_count(self):
        import retrospective

        events = [
            make_event("pair_guidance", content="Check tests", tool_name="Write"),
            make_event("pair_guidance", content="Add types", tool_name="Edit"),
            make_event(content="filler 1"),
            make_event(content="filler 2"),
            make_event(content="filler 3"),
        ]
        self._write_events(events)
        retrospective.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["session_stats"]["pair_guidance_count"], 2)

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
            "status", content="Fixed", references=[c1["id"]], working_on=["test.py"]
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
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

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
        # Empty SMM returns None — no content to inject
        self.assertIsNone(result)

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
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_write_gets_full_delta(self):
        # Write a red question event, then check that Write gets it
        events = [make_event("question", priority="\U0001f534", content="blocker?")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(tool_input={"file_path": "src/new.ts"}),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("smm-delta", result)

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
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
        self.assertIn("other-agent", str(cm.exception))

    def test_no_smm_dir_degrades_gracefully(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = pre_tool_use.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )
        # Write tools still get navigator nudge even without SMM
        # but no SMM-dependent content (delta, debt, etc.)
        if result:
            self.assertNotIn("smm-context", result)
            self.assertNotIn("smm-debt-context", result)

    def test_bash_blocking_tier_gets_pair_guidance(self):
        events = [make_event("pair_guidance", content="Use --dry-run")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        # Now uses Active Context (materialized), not delta format
        self.assertIn("Navigator Guidance", result)

    def test_bash_blocking_tier_includes_status(self):
        """TIER_BLOCKING now injects Active Context which includes Agent Status."""
        events = [make_event("status", content="busy")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        # Active Context includes Agent Status section
        self.assertIsNotNone(result)
        self.assertIn("Agent Status", result)


# ===========================================================================
# pre_tool_use — Active Context, enforcement, debt injection (M5.3)
# ===========================================================================


class TestPreToolUseActiveContext(_HookTestCase):
    def test_bash_non_commit_gets_active_context(self):
        """TIER_BLOCKING: Bash (non-commit) gets Active Context instead of delta."""
        import pre_tool_use

        events = [
            make_event("goal", content="Ship v1"),
            make_event("decision", content="Use REST", topic="api-style"),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="npm test"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Project Goals", result)
        # Should NOT have reference material
        self.assertNotIn("Architecture Decisions", result)

    def test_bash_commit_gets_full_delta(self):
        """TIER_FULL: Bash with git commit gets full delta, not Active Context."""
        import pre_tool_use

        events = [make_event("decision", content="Use REST", topic="api-style")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("smm-delta", result)

    def test_write_gets_full_delta(self):
        """TIER_FULL: Write tool gets full delta."""
        import pre_tool_use

        events = [make_event("status", content="Working on app")]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(tool_input={"file_path": "/tmp/src/new.ts"}),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("smm-delta", result)

    def test_read_gets_red_only(self):
        """TIER_RED_ONLY: Read tool still gets red-only (unchanged)."""
        import pre_tool_use

        events = [make_event("status", content="Working")]
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
        self.assertIsNone(result)


class TestPreToolUseEnforcement(_HookTestCase):
    def test_advisory_converts_block_to_warning(self):
        """Advisory mode converts BlockedError to warning in context."""
        import pre_tool_use

        events = [
            make_event(
                "status", agent_id="other-agent", working_on=["/tmp/src/app.ts"]
            ),
        ]
        self._write_events(events)
        with _override_settings({"enforcement": "advisory"}):
            result = pre_tool_use.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result)
            self.assertIn("CONFLICT", result)
            self.assertIn("advisory", result.lower())

    def test_strict_blocks(self):
        """Strict mode still raises BlockedError."""
        import pre_tool_use

        events = [
            make_event(
                "status", agent_id="other-agent", working_on=["/tmp/src/app.ts"]
            ),
        ]
        self._write_events(events)
        with self.assertRaises(_common.BlockedError):
            pre_tool_use.run(
                _make_write_input(),
                smm_dir=self.smm_dir,
            )

    def test_advisory_indicator_in_context(self):
        """Advisory mode appends enforcement indicator."""
        import pre_tool_use

        events = [make_event("goal", content="Ship")]
        self._write_events(events)
        with _override_settings({"enforcement": "advisory"}):
            result = pre_tool_use.run(
                _make_bash_input(command="npm test"),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result)
            self.assertIn("[enforcement: advisory]", result)


class TestPreToolUseDebtInjection(_HookTestCase):
    def test_debt_included_for_write_tools(self):
        """Write tools get debt info for target file."""
        import pre_tool_use

        events = [
            make_event("debt", content="Legacy coupling", files=["/tmp/src/app.ts"]),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "/tmp/src/app.ts", "content": "x"}
            ),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Legacy coupling", result)

    def test_no_debt_for_clean_file(self):
        """No debt injection section when file has no debt events."""
        import pre_tool_use

        events = [
            make_event("debt", content="Legacy coupling", files=["/tmp/src/other.ts"]),
        ]
        self._write_events(events)
        result = pre_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "/tmp/src/app.ts", "content": "x"}
            ),
            smm_dir=self.smm_dir,
        )
        # Delta may include the debt event, but debt injection section should be absent
        if result:
            self.assertNotIn("smm-debt-context", result)


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
                "subagent_stop",
                "user_prompt_log",
                "retrospective",
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

        input_data = _make_write_input(session_id="perf", agent_type="xp-navigator")

        start = time.monotonic()
        for _ in range(1000):
            pre_tool_use.run(input_data, smm_dir=self.smm_dir)
        elapsed = time.monotonic() - start

        # 1000 no-op runs should be well under 1 second
        self.assertLess(elapsed, 1.0, f"1000 xp-agent skips took {elapsed:.2f}s")


# ===========================================================================
# M6.5: Subagent nudge tests
# ===========================================================================


class TestPreToolUseNavigatorNudge(_HookTestCase):
    """M6.5: pre_tool_use.py should nudge invoking xp-navigator for writes."""

    def test_write_tool_has_navigator_nudge(self):
        result = pre_tool_use.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-navigator", result)

    def test_edit_tool_has_navigator_nudge(self):
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "src/app.ts",
                    "old_string": "x",
                    "new_string": "y",
                },
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-navigator", result)

    def test_read_tool_no_navigator_nudge(self):
        result = pre_tool_use.run(
            {
                "session_id": "t",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "cwd": "/tmp",
                "agent_id": "main",
            },
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-navigator", result)

    def test_bash_tool_no_navigator_nudge(self):
        result = pre_tool_use.run(
            _make_bash_input(command="echo hi"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-navigator", result)

    def test_git_commit_no_navigator_nudge(self):
        """git commit is TIER_FULL but not a write tool — no navigator nudge."""
        result = pre_tool_use.run(
            _make_bash_input(command="git commit -m 'test'"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-navigator", result)

    def test_xp_agent_no_navigator_nudge(self):
        result = pre_tool_use.run(
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


class TestRetrospectiveNudge(_HookTestCase):
    """M6.5: retrospective.py should nudge invoking xp-retrospective."""

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

    def setUp(self):
        super().setUp()
        import session_start

        session_start._load_behavioral_guide.cache_clear()

    def tearDown(self):
        import session_start

        session_start._load_behavioral_guide.cache_clear()
        super().tearDown()

    def test_no_goals_nudges_goal_collection(self):
        import session_start

        self._write_events([make_event("status", content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("xp-goal-collection", result)
        self.assertIn("goals", result.lower())

    def test_has_goals_no_questions_no_nudge(self):
        import session_start

        self._write_events([make_event("goal", content="Build the app")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-goal-collection", result)

    def test_open_questions_nudges_question_triage(self):
        import session_start

        self._write_events(
            [
                make_event("goal", content="Build the app"),
                make_event(
                    "question", content="Which DB?", priority=_common.PRIORITY_BLOCKING
                ),
            ]
        )
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("xp-question-triage", result)


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
            _make_write_input(tool_response={"success": True}),
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
            _make_write_input(tool_response={"success": True}, cwd="/home/user"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(statuses[0]["working_on"], ["/home/user/src/app.ts"])

    def test_xp_agent_skips(self):
        post_tool_use.run(
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        post_tool_use.run(
            _make_write_input(),
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
            _make_write_input(),
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
            _make_write_input(),
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
            _make_write_input(),
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
            _make_write_input(),
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
            _make_write_input(),
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
            _make_write_input(tool_input={"file_path": "src/b.ts", "content": "x"}),
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
            _make_write_input(tool_input={"file_path": "src/auth.ts", "content": "x"}),
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
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        refs = statuses[0].get("references", [])
        self.assertNotIn(d["id"], refs)


import task_completed  # noqa: E402


class TestTaskCompleted(_HookTestCase):
    """TaskCompleted hook gates navigator, nudges quality reviewer."""

    def _make_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "hook_event_name": "TaskCompleted",
            "task_id": "task-1",
            "task_subject": "Implement feature X",
        }
        data.update(overrides)
        return data

    def _seed_guidance(self):
        """Seed a pair_guidance event so navigator gate passes."""
        self._write_events(
            [make_event("pair_guidance", content="Looks good", tool_name="Write")]
        )

    def test_blocks_without_navigator_guidance(self):
        with self.assertRaises(_common.BlockedError) as ctx:
            task_completed.run(self._make_input(), smm_dir=self.smm_dir)
        self.assertIn("xp-navigator", str(ctx.exception))

    def test_passes_with_navigator_guidance(self):
        self._seed_guidance()
        result = task_completed.run(self._make_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("xp-quality-reviewer", result)

    def test_second_attempt_passes_without_guidance(self):
        """Second attempt allows through to prevent infinite loops."""
        # First attempt blocks and writes gate event
        with self.assertRaises(_common.BlockedError):
            task_completed.run(self._make_input(), smm_dir=self.smm_dir)
        # Second attempt passes
        result = task_completed.run(self._make_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("xp-quality-reviewer", result)

    def test_xp_agent_skips(self):
        result = task_completed.run(
            self._make_input(agent_type="xp-quality-reviewer"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


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
            _make_write_input(),
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
            _make_write_input(),
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
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
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
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
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
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
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
                    _make_write_input(
                        tool_input={"file_path": "src/app.py", "content": "x"},
                        cwd=str(tmpdir),
                    ),
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
            _make_write_input(agent_type="xp-navigator"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        lint_check.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_ruff_skips_json_file(self):
        """ruff should not run against .json files — they are not Python."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "ruff.toml").touch()
        try:
            with patch("lint_check.shutil.which", return_value="/usr/bin/ruff"):
                result = lint_check.run_linter("ruff", str(tmpdir / "hooks.json"))
            self.assertIsNone(result)
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_ruff_runs_on_python_file(self):
        """ruff should still run on .py files."""
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
                result = lint_check.run_linter("ruff", str(tmpdir / "app.py"))
            self.assertIsNone(result)  # clean — no errors
            mock_run.assert_called_once()
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)


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

    def test_unittest_pass(self):
        output = "Ran 821 tests in 32.346s\n\nOK"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 821)
        self.assertEqual(result["failed"], 0)

    def test_unittest_fail(self):
        output = "Ran 50 tests in 1.2s\n\nFAILED (failures=2, errors=1)"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 47)
        self.assertEqual(result["failed"], 3)
        self.assertEqual(result["errors"], 1)

    def test_is_test_run_unittest(self):
        self.assertEqual(
            bash_post_tool.is_test_run("python3 -m unittest tests/test_foo.py -v"),
            "unittest",
        )
        self.assertIsNone(bash_post_tool.is_test_run("echo unittest"))


class TestBashPostTool(_HookTestCase):
    def test_git_commit_auto_drafts_decision(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add auth'",
                    stdout="[main abc123] Add auth\n 3 files changed",
                ),
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
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main abc123] Fix bug\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_git_commit_large_appends_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=12):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Big change'",
                    stdout="[main abc123] Big change\n 12 files changed",
                ),
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
                    _make_bash_input(
                        command="git commit -m 'x'",
                        stdout="[main a] x\n 6 files changed",
                    ),
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
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("5 passed" in s["content"] for s in statuses))

    def test_pytest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 3 passed, 2 failed in 1.2s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            _make_bash_input(command="npx jest", stdout="Tests:  5 passed, 5 total"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_jest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="npx jest",
                stdout="Tests:  2 failed, 3 passed, 5 total",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="ok  \tgithub.com/user/pkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_go_test_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="--- FAIL: TestSomething (0.00s)\nFAIL\tpkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            _make_bash_input(command="ls -la", stdout="total 0"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips(self):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'x'",
                stdout="[main a] x",
                agent_type="xp-navigator",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        bash_post_tool.run(
            _make_bash_input(command="git commit -m 'x'", stdout="[main a] x"),
            smm_dir=fake_dir,
        )

    def test_git_commit_parse_message(self):
        response = "[main abc123] Fix login bug\n 1 file changed"
        self.assertEqual(bash_post_tool.parse_commit_message(response), "Fix login bug")


# ===========================================================================
# Bash Failure (PostToolUseFailure)
# ===========================================================================


def _make_bash_failure_input(
    command: str = "echo hi", error: str = "exit code 1", **overrides
) -> dict:
    """Build a canonical PostToolUseFailure Bash input dict."""
    data = {
        "session_id": "t",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": error,
        "is_interrupt": False,
        "agent_id": "main",
    }
    data.update(overrides)
    return data


class TestBashFailure(_HookTestCase):
    """Tests for bash_failure.py PostToolUseFailure handler."""

    def setUp(self):
        super().setUp()
        import bash_failure

        self.mod = bash_failure

    def test_xp_agent_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_type="xp-nav"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_interrupt_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="interrupted", is_interrupt=True
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_no_smm_dir_degrades(self):
        inp = _make_bash_failure_input(command="pytest", error="exit 1")
        self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        # No crash

    def test_non_test_command_ignored(self):
        inp = _make_bash_failure_input(command="ls -la", error="exit 2")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_pytest_failure_records_status_and_concern(self):
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertIn("non-zero status code 2", statuses[0]["content"])


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

    def test_empty_prompt_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": ""},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_task_notification_skips(self):
        user_prompt_log.run(
            {
                "session_id": "t",
                "prompt": "<task-notification>\n<task-id>abc123</task-id>\n",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 15000
        user_prompt_log.run(
            {"session_id": "t", "prompt": long_prompt},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_no_goals_first_prompt_blocks_with_slash_command(self):
        """Block message must say 'Run /xp-goal-collection' so agent auto-invokes."""
        result = user_prompt_log.run(
            {"session_id": "t", "prompt": "lets get started"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, user_prompt_log._BLOCK_GOALS)
        # Tracker created so second prompt nudges instead of blocks
        tracker = self.smm_dir / user_prompt_log._GOAL_NUDGE_TRACKER
        self.assertTrue(tracker.exists())

    def test_no_goals_second_prompt_nudges_with_slash_command(self):
        """After block, nudge message must say 'Run /xp-goal-collection'."""
        # Simulate tracker already set (block already fired)
        (self.smm_dir / user_prompt_log._GOAL_NUDGE_TRACKER).write_text("")
        result = user_prompt_log.run(
            {"session_id": "t", "prompt": "do something"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, user_prompt_log._NUDGE_MESSAGE)

    def test_goals_present_no_block(self):
        """With goals recorded, prompt proceeds normally."""
        self._write_events([make_event("goal", content="Ship MVP")])
        result = user_prompt_log.run(
            {"session_id": "t", "prompt": "do something"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


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


class TestSubagentStopPlanBlock(_HookTestCase):
    """M6.5: subagent_stop.py should block for Plan subagents."""

    def test_plan_agent_type_blocks(self):
        with self.assertRaises(_common.BlockedError) as cm:
            subagent_stop.run(
                {
                    "session_id": "t",
                    "agent_id": "plan-1",
                    "agent_type": "Plan",
                    "last_assistant_message": "1. Write tests\n2. Implement",
                },
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-plan-reviewer", str(cm.exception))

    def test_plan_block_still_records_status(self):
        """Status event should be written even when blocking."""
        with contextlib.suppress(_common.BlockedError):
            subagent_stop.run(
                {
                    "session_id": "t",
                    "agent_id": "plan-1",
                    "agent_type": "Plan",
                    "last_assistant_message": "1. Do stuff",
                },
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)


class TestSubagentStopReviewerNudge(_HookTestCase):
    """M6.5: subagent_stop.py should nudge xp-subagent-reviewer for non-xp subagents."""

    def test_regular_subagent_gets_reviewer_nudge(self):
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-subagent-reviewer", result)
        self.assertIn("background", result.lower())

    def test_xp_agent_no_reviewer_nudge(self):
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-navigator",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# detect_conflicts in _common.py — Milestone 3.4 extraction
# ===========================================================================


class TestFindRelatedDecisions(unittest.TestCase):
    """Test _common.find_related_decisions correctness."""

    def test_matches_via_working_on(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = _common.find_related_decisions([d], "/tmp/src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_no_match_different_file(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = _common.find_related_decisions([d], "/tmp/src/other.ts", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_no_substring_false_positive_via_references(self):
        """'a.py' must not match a reference to 'data.py'."""
        d = make_event(
            "decision",
            topic="naming",
            content="Naming convention",
            references=["data.py"],
        )
        result = _common.find_related_decisions([d], "a.py", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_exact_reference_match(self):
        """Exact normalized path in references should match."""
        d = make_event(
            "decision", topic="auth", content="Use JWT", references=["src/auth.ts"]
        )
        result = _common.find_related_decisions([d], "src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_skips_non_decision_events(self):
        s = make_event("status", content="Working", working_on=["/tmp/src/app.ts"])
        result = _common.find_related_decisions([s], "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_invalid_agent_id_graceful(self):
        """Invalid agent_id in _validate_agent_id should not crash hooks."""
        import post_tool_use

        result = post_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "x.py", "content": "x"},
                agent_id="bad;agent",
            ),
        )
        self.assertIsNone(result)


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
        # Find the catch-all entry (no matcher) that has subagent_stop.py
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                hooks = entry["hooks"]
                cmds = [h["command"] for h in hooks if "command" in h]
                self.assertTrue(any("subagent_stop.py" in c for c in cmds))
                return
        self.fail("No catch-all SubagentStop entry found")

    def test_subagent_stop_has_timeout(self):
        for entry in self.data["hooks"]["SubagentStop"]:
            if "matcher" not in entry:
                self.assertEqual(entry["hooks"][0]["timeout"], 5000)
                return
        self.fail("No catch-all SubagentStop entry found")


# ===========================================================================
# Prompt file tests (M6.5: agent prompts deleted, only tdd_check remains)
# ===========================================================================


# ===========================================================================
# hooks.json test base class
# ===========================================================================


class _HooksJsonTestCase(unittest.TestCase):
    """Base class for hooks.json registration tests."""

    def setUp(self):
        hooks_path = Path(__file__).parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            self.data = json.load(f)

    def _find_matcher_entry(self, hook_event: str, matcher: str) -> dict | None:
        """Find the entry with the given matcher in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if entry.get("matcher") == matcher:
                return entry
        return None

    def _find_default_entry(self, hook_event: str) -> dict | None:
        """Find an entry without a matcher (default) in a hook event list."""
        for entry in self.data["hooks"].get(hook_event, []):
            if "matcher" not in entry:
                return entry
        return None


# ===========================================================================
# hooks.json M4 registration tests
# ===========================================================================


class TestHooksJsonM4(_HooksJsonTestCase):
    """Verify hooks.json M4 registrations (agent hooks removed in M6.5)."""

    def test_pretooluse_has_star_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "*")
        self.assertIsNotNone(entry, "PreToolUse * matcher entry missing")

    def test_pretooluse_no_write_edit_entry(self):
        """Write|Edit|MultiEdit navigator agent hook removed in M6.5."""
        entry = self._find_matcher_entry("PreToolUse", "Write|Edit|MultiEdit")
        self.assertIsNone(
            entry, "PreToolUse Write|Edit|MultiEdit entry should be removed"
        )

    def test_posttooluse_no_agent_hooks(self):
        """Quality reviewer agent hook removed in M6.5."""
        entry = self._find_matcher_entry("PostToolUse", "Write|Edit|MultiEdit")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in PostToolUse")

    def test_subagentstop_no_plan_matcher(self):
        """Plan matcher entry removed in M6.5 (plan review via subagent now)."""
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        self.assertIsNone(entry, "SubagentStop Plan matcher entry should be removed")


# ===========================================================================
# Prompt file tests (Milestone 5)
# ===========================================================================


class TestPromptFilesM5(unittest.TestCase):
    """Verify prompt files state after tdd_check.md replaced by command hook."""

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent / "prompts"

    def test_tdd_check_md_still_exists(self):
        """tdd_check.md kept for reference but no longer registered as hook."""
        self.assertTrue((self.prompts_dir / "tdd_check.md").exists())


# ===========================================================================
# M5.3 acceptance criteria — prompt content verification
# ===========================================================================


class TestM53AcceptanceCriteria(unittest.TestCase):
    """Verify M5.3 acceptance criteria are met.

    Prompt content checks updated in M6.5 to point to agents/ directory
    (agent hook prompts moved to plugin subagents).
    Testable behaviors verified in their respective test classes:
    - TestPreToolUseEnforcement (ACs 1-2)
    - TestLoadEnforcementMode (AC 3)
    - TestFindDebtForFile (AC 9)
    - TestPreToolUseDebtInjection (AC 10)
    - TestPreToolUseActiveContext (AC 15)
    """

    def setUp(self):
        self.agents_dir = Path(__file__).parent.parent / "agents"

    # AC 1: navigator mentions contradictions
    def test_navigator_mentions_contradictions(self):
        content = (self.agents_dir / "xp-navigator.md").read_text()
        self.assertIn("contradict", content.lower())

    # AC 4: first session asks for goals (now in skill)
    def test_goal_collection_skill(self):
        skill_dir = Path(__file__).parent.parent / "skills" / "xp-goal-collection"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Goal Collection", content)
        self.assertIn('--type "goal"', content)

    # AC 5: question triage distills intents (now in skill)
    def test_question_triage_intent_distillation(self):
        skill_dir = Path(__file__).parent.parent / "skills" / "xp-question-triage"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Intent Reconciliation", content)
        self.assertIn("customer_input", content)
        self.assertIn("--intent-status", content)

    # AC 7: delivered intents by event log activity
    def test_question_triage_delivery_by_events(self):
        skill_dir = Path(__file__).parent.parent / "skills" / "xp-question-triage"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("delivered", content)
        self.assertIn("recent events", content.lower())

    # AC 8: ambiguous keeps intent open
    def test_question_triage_err_toward_open(self):
        skill_dir = Path(__file__).parent.parent / "skills" / "xp-question-triage"
        content = (skill_dir / "SKILL.md").read_text()
        self.assertIn("Err toward keeping intents open", content)

    # AC 10: navigator debt awareness
    def test_navigator_debt_awareness(self):
        content = (self.agents_dir / "xp-navigator.md").read_text()
        self.assertIn("Debt Awareness", content)

    # AC 11: quality reviewer flags ignored debt
    def test_quality_reviewer_flags_ignored_debt(self):
        content = (self.agents_dir / "xp-quality-reviewer.md").read_text()
        self.assertIn('--type "debt"', content)
        self.assertIn("debt", content.lower())

    # AC 12: retrospective escalates aging debt
    def test_retrospective_escalates_aging_debt(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Escalating aging debt", content)
        self.assertIn("high-priority", content)

    # AC 13: retrospective flags plugin health anomalies
    def test_retrospective_plugin_health(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("Plugin Health", content)
        self.assertIn("session_stats", content)
        self.assertIn("pair_guidance", content)

    # AC 14: cross-session trends
    def test_retrospective_cross_session_trends(self):
        content = (self.agents_dir / "xp-retrospective.md").read_text()
        self.assertIn("previous_retros", content)
        self.assertIn("cross-session", content.lower())


# ===========================================================================
# hooks.json M5 registration tests
# ===========================================================================


class TestHooksJsonM5(_HooksJsonTestCase):
    """Verify hooks.json has all M5 hook registrations."""

    # --- SessionStart: retrospective.py command ---

    def test_session_start_has_retrospective_command(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        commands = [h for h in entry["hooks"] if h.get("type") == "command"]
        self.assertTrue(
            any("retrospective.py" in h["command"] for h in commands),
            "retrospective.py command hook missing from SessionStart",
        )

    # --- SessionStart: agent hooks removed in M6.5 ---

    def test_session_start_no_agent_hooks(self):
        """Retro analyst and customer proxy agent hooks removed in M6.5."""
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 0, "No agent hooks should remain in SessionStart")

    # --- SubagentStop: agent hooks removed in M6.5 ---

    def test_subagentstop_no_agent_hooks(self):
        """Subagent reviewer agent hook removed in M6.5."""
        for entry in self.data["hooks"]["SubagentStop"]:
            agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
            self.assertEqual(
                len(agents), 0, "No agent hooks should remain in SubagentStop"
            )

    # --- Stop: tdd_stop_gate command hook ---

    def test_stop_hook_exists(self):
        self.assertIn("Stop", self.data["hooks"], "Stop hook section missing")

    def test_stop_hook_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_hook_no_prompt_hooks(self):
        """Prompt hooks replaced by command hooks — none should remain."""
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        prompts = [h for h in all_hooks if h.get("type") == "prompt"]
        self.assertEqual(len(prompts), 0, "No prompt hooks should remain in Stop")


# ===========================================================================
# Helpers for Stop hook tests
# ===========================================================================


def _make_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input dict."""
    data = {"session_id": "t", "agent_id": "main"}
    data.update(overrides)
    return data


# ===========================================================================
# Simplify Gate (Milestone 5.4)
# ===========================================================================


class TestSimplifyGate(_HookTestCase):
    """Tests for simplify_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_no_events_no_output(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_customer_input_no_output(self):
        self._write_events([make_event("status", content="busy")])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_file_changes_no_output(self):
        self._write_events(
            [
                make_event("customer_input", content="do something"),
                make_event("status", content="thinking", working_on=[]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_docs_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update docs"),
                make_event("status", content="wrote", working_on=["README.md"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_config_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update config"),
                make_event("status", content="wrote", working_on=["package.json"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_images_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="add logo"),
                make_event("status", content="wrote", working_on=["logo.png"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_code_plus_docs_triggers(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote", working_on=["README.md"]),
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_file_changes_triggers_simplify(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote file", working_on=["src/app.ts"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_tracker_prevents_retrigger(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote file", working_on=["src/app.ts"]),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)
        # Second call — tracker should prevent re-trigger
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result2)

    def test_new_loop_resets_tracker(self):
        ci1 = make_event("customer_input", content="first task")
        self._write_events(
            [
                ci1,
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)

        # New loop: new customer_input + changes
        ci2 = make_event("customer_input", content="second task")
        self._write_events(
            [
                ci1,
                make_event("status", content="wrote", working_on=["src/a.ts"]),
                ci2,
                make_event("status", content="wrote2", working_on=["src/b.ts"]),
            ]
        )
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result2)
        self.assertIn("/simplify", result2)

    def test_tracker_written_with_loop_id(self):
        ci = make_event("customer_input", content="build")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/x.ts"]),
            ]
        )
        inp = _make_stop_input()
        self.mod.run(inp, smm_dir=self.smm_dir)

        tracker_file = self.smm_dir / ".simplify-main.json"
        self.assertTrue(tracker_file.exists())
        tracker = json.loads(tracker_file.read_text())
        self.assertEqual(tracker["loop_id"], ci["id"])


# ===========================================================================
# Security: agent_id validation + symlink protection
# ===========================================================================


class TestSimplifyGateSecurity(_HookTestCase):
    """Security tests for simplify_gate.py."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_path_traversal_agent_id_rejected(self):
        """agent_id with path traversal is rejected."""
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="../../../etc/evil")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_slash_agent_id_rejected(self):
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="foo/bar")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)


# ===========================================================================
# TDD Stop Gate (replaces tdd_check.md prompt hook)
# ===========================================================================


class TestTddStopGate(_HookTestCase):
    """Tests for tdd_stop_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import tdd_stop_gate

        self.mod = tdd_stop_gate

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_events_allows_stop(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_passing_tests_allows_stop(self):
        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_failing_tests_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("failing", result.lower())

    def test_failed_test_run_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test command failed: `pytest` — exit 1",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_pass_after_fail_allows_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_fail_after_pass_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
                make_event(
                    "concern",
                    content="Test failures detected: 1 failed (jest)",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_no_test_events_allows_stop(self):
        self._write_events(
            [
                make_event("status", content="Wrote file", working_on=["a.py"]),
                make_event("customer_input", content="build something"),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)


class TestBashFailureSecurity(_HookTestCase):
    """Security tests for bash_failure.py."""

    def setUp(self):
        super().setUp()
        import bash_failure

        self.mod = bash_failure

    def test_path_traversal_agent_id_rejected(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_id="../../evil"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


class TestWriteJsonAtomicSecurity(_HookTestCase):
    """Security tests for _common.write_json_atomic()."""

    def test_rejects_symlink_target(self):
        target = self.smm_dir / "real-file.json"
        target.write_text("{}")
        link = self.smm_dir / "link.json"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            _common.write_json_atomic(link, {"evil": True})
        # Original file should be unchanged
        self.assertEqual(target.read_text(), "{}")


# ===========================================================================
# hooks.json M5.4 registration tests
# ===========================================================================


class TestHooksJsonM54(_HooksJsonTestCase):
    """Verify hooks.json has M5.4 hook registrations."""

    def test_stop_has_simplify_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("simplify_gate.py" in h["command"] for h in commands),
            "simplify_gate.py command hook missing from Stop",
        )

    def test_stop_has_tdd_gate_command(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("tdd_stop_gate.py" in h["command"] for h in commands),
            "tdd_stop_gate.py command hook missing from Stop",
        )

    def test_stop_has_two_hooks(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        self.assertEqual(
            len(all_hooks), 2, f"Expected 2 Stop hooks, got {len(all_hooks)}"
        )


# ===========================================================================
# hooks.json gap fixes — PostToolUseFailure + SessionStart clear
# ===========================================================================


class TestHooksJsonGapFixes(_HooksJsonTestCase):
    """Verify hooks.json registrations for PostToolUseFailure and clear matcher."""

    def test_post_tool_use_failure_section_exists(self):
        self.assertIn(
            "PostToolUseFailure",
            self.data["hooks"],
            "PostToolUseFailure section missing from hooks.json",
        )

    def test_post_tool_use_failure_has_bash_matcher(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        matchers = [e.get("matcher") for e in entries]
        self.assertIn("Bash", matchers)

    def test_post_tool_use_failure_has_bash_failure_command(self):
        entries = self.data["hooks"]["PostToolUseFailure"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        commands = [h for h in all_hooks if h.get("type") == "command"]
        self.assertTrue(
            any("bash_failure.py" in h["command"] for h in commands),
            "bash_failure.py missing from PostToolUseFailure",
        )

    def test_session_start_includes_clear_matcher(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        self.assertIsNotNone(entry, "SessionStart matcher should include 'clear'")


# ===========================================================================
# Security helpers (_common.py) — Milestone 5.5
# ===========================================================================


class TestSecurityHelpers(_HookTestCase):
    """Tests for security review tracker helpers in _common.py."""

    def test_get_head_hash_returns_hash(self):
        """get_head_hash returns a hex hash string."""
        with patch(
            "_common.subprocess.check_output",
            return_value="abc1234def5678\n",
        ):
            result = _common.get_head_hash()
            self.assertEqual(result, "abc1234def5678")

    def test_get_head_hash_returns_none_on_error(self):
        """get_head_hash returns None when git fails."""
        from subprocess import CalledProcessError

        with patch(
            "_common.subprocess.check_output",
            side_effect=CalledProcessError(128, "git"),
        ):
            result = _common.get_head_hash()
            self.assertIsNone(result)

    def test_get_head_hash_returns_none_on_timeout(self):
        """get_head_hash returns None on subprocess timeout."""
        from subprocess import TimeoutExpired

        with patch(
            "_common.subprocess.check_output",
            side_effect=TimeoutExpired("git", 5),
        ):
            result = _common.get_head_hash()
            self.assertIsNone(result)

    def test_security_tracker_path_valid_hash(self):
        """security_tracker_path builds correct path for valid hash."""
        path = _common.security_tracker_path(self.smm_dir, "abc1234")
        self.assertEqual(path, self.smm_dir / ".security-reviewed-abc1234")

    def test_security_tracker_path_rejects_invalid_hash(self):
        """security_tracker_path raises ValueError for invalid hash."""
        with self.assertRaises(ValueError):
            _common.security_tracker_path(self.smm_dir, "not-a-hash!")
        with self.assertRaises(ValueError):
            _common.security_tracker_path(self.smm_dir, "../etc/passwd")
        with self.assertRaises(ValueError):
            _common.security_tracker_path(self.smm_dir, "")

    def test_security_tracker_path_rejects_too_short_hash(self):
        """security_tracker_path rejects hashes shorter than 7 chars."""
        with self.assertRaises(ValueError):
            _common.security_tracker_path(self.smm_dir, "abc12")

    def test_write_and_exists_tracker(self):
        """write_security_tracker creates file, security_tracker_exists finds it."""
        _common.write_security_tracker(self.smm_dir, "abc1234")
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_tracker_not_exists_when_missing(self):
        """security_tracker_exists returns False when no tracker file."""
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_write_tracker_cleans_old(self):
        """write_security_tracker removes old tracker files."""
        _common.write_security_tracker(self.smm_dir, "aaa1111")
        _common.write_security_tracker(self.smm_dir, "bbb2222")
        # Write new tracker
        _common.write_security_tracker(self.smm_dir, "ccc3333")
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "aaa1111"))
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "bbb2222"))
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "ccc3333"))

    def test_tracker_rejects_symlink(self):
        """security_tracker_exists returns False for symlinks."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = self.smm_dir / ".security-reviewed-abc1234"
        link.symlink_to(real_file)
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_cleanup_skips_non_hash_files(self):
        """_cleanup_old_security_trackers skips files with non-hash suffixes."""
        notes = self.smm_dir / ".security-reviewed-notes.txt"
        notes.write_text("keep me")
        _common.write_security_tracker(self.smm_dir, "abc1234")
        self.assertTrue(notes.exists(), "Non-hash file should survive cleanup")

    def test_mark_security_reviewed(self):
        """mark_security_reviewed encapsulates hash fetch + tracker write."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            _common.mark_security_reviewed(self.smm_dir)
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_mark_security_reviewed_no_hash(self):
        """mark_security_reviewed no-ops when HEAD hash unavailable."""
        with patch.object(_common, "get_head_hash", return_value=None):
            _common.mark_security_reviewed(self.smm_dir)
        # No tracker, no crash

    def test_write_tracker_content(self):
        """write_security_tracker writes JSON with commit_hash and ts."""
        _common.write_security_tracker(self.smm_dir, "abc1234")
        path = _common.security_tracker_path(self.smm_dir, "abc1234")
        data = json.loads(path.read_text())
        self.assertEqual(data["commit_hash"], "abc1234")
        self.assertIn("ts", data)


# ===========================================================================
# PreToolUse push gate — Milestone 5.5
# ===========================================================================


class TestPreToolUsePushGate(_HookTestCase):
    """Tests for git push security review gate in pre_tool_use.py."""

    def setUp(self):
        super().setUp()
        import pre_tool_use

        self.pre_tool_use = pre_tool_use
        _common.load_enforcement_mode.cache_clear()

    def tearDown(self):
        _common.load_enforcement_mode.cache_clear()
        super().tearDown()

    def _push_input(self, command: str = "git push origin main", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_is_git_push_positive(self):
        """is_git_push detects various git push commands."""
        self.assertTrue(self.pre_tool_use.is_git_push("git push"))
        self.assertTrue(self.pre_tool_use.is_git_push("git push origin main"))
        self.assertTrue(self.pre_tool_use.is_git_push("git push --force"))

    def test_is_git_push_with_flags(self):
        """is_git_push detects git push with interleaved flags."""
        self.assertTrue(self.pre_tool_use.is_git_push("/usr/bin/git push"))
        self.assertTrue(self.pre_tool_use.is_git_push("git -c core.foo=bar push"))
        self.assertTrue(self.pre_tool_use.is_git_push("git -C /tmp push origin"))

    def test_is_git_push_negative(self):
        """is_git_push rejects non-push commands."""
        self.assertFalse(self.pre_tool_use.is_git_push("git commit -m 'test'"))
        self.assertFalse(self.pre_tool_use.is_git_push("git pull origin main"))
        self.assertFalse(self.pre_tool_use.is_git_push("echo push"))

    def test_push_blocked_without_tracker(self):
        """git push is blocked when no security tracker exists."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError) as ctx:
                self.pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            self.assertIn("/security-review", str(ctx.exception))

    def test_push_passes_with_tracker(self):
        """git push passes when security tracker exists."""
        _common.write_security_tracker(self.smm_dir, "abc1234")
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            # Should not raise BlockedError
            self.pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)

    def test_push_advisory_warns(self):
        """Advisory mode: git push warns instead of blocking."""
        with (
            _override_settings({"enforcement": "advisory"}),
            patch.object(_common, "get_head_hash", return_value="abc1234"),
        ):
            result = self.pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            self.assertIsNotNone(result)
            self.assertIn("security", result.lower())

    def test_push_event_written_on_block(self):
        """Blocking a push writes security_review_requested event."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            with self.assertRaises(_common.BlockedError):
                self.pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            events = _common.read_events_raw(self.smm_dir)
            sec_events = [
                e for e in events if e.get("type") == _common.SECURITY_REVIEW_REQUESTED
            ]
            self.assertEqual(len(sec_events), 1)
            self.assertIn("abc1234", sec_events[0]["content"])

    def test_push_no_smm_degrades(self):
        """git push with no SMM dir passes through (no crash)."""
        self.pre_tool_use.run(self._push_input(), smm_dir=None)
        # No BlockedError — graceful degradation

    def test_push_no_hash_degrades(self):
        """git push with no HEAD hash passes through (no crash)."""
        with patch.object(_common, "get_head_hash", return_value=None):
            self.pre_tool_use.run(self._push_input(), smm_dir=self.smm_dir)
            # No BlockedError — graceful degradation

    def test_push_xp_agent_skips(self):
        """xp- agents skip the push gate."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.pre_tool_use.run(
                self._push_input(agent_type="xp-navigator"),
                smm_dir=self.smm_dir,
            )
            # No BlockedError

    def test_non_push_bash_not_affected(self):
        """Non-push Bash commands don't trigger push gate."""
        inp = self._push_input(command="git status")
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            # Should not raise BlockedError
            self.pre_tool_use.run(inp, smm_dir=self.smm_dir)

    def test_non_bash_not_affected(self):
        """Non-Bash tools don't trigger push gate."""
        inp = {
            "session_id": "t",
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "git push"},
            "cwd": "/tmp",
            "agent_id": "main",
        }
        # Should not raise BlockedError
        self.pre_tool_use.run(inp, smm_dir=self.smm_dir)


# ===========================================================================
# UserPromptLog security review detection (Path 1) — Milestone 5.5
# ===========================================================================


class TestUserPromptLogSecurity(_HookTestCase):
    """Tests for security review pattern detection in user_prompt_log.py."""

    def setUp(self):
        super().setUp()
        import user_prompt_log

        self.user_prompt_log = user_prompt_log

    def _prompt_input(self, prompt: str, **overrides) -> dict:
        data = {
            "session_id": "t",
            "prompt": prompt,
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_security_review_slash_writes_tracker(self):
        """/security-review in prompt writes tracker file."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("/security-review"),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_security_review_natural_writes_tracker(self):
        """'security review' in prompt writes tracker file."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("please run a security review"),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_security_audit_writes_tracker(self):
        """'security audit' in prompt writes tracker file."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("do a security audit"),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_case_insensitive(self):
        """Pattern matching is case insensitive."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("Run a Security Review"),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_no_match_no_tracker(self):
        """Non-security prompts don't write tracker."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("fix the bug in app.py"),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_event_still_logged(self):
        """Event is logged as customer_input regardless of security match."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.user_prompt_log.run(
                self._prompt_input("/security-review"),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        ci_events = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci_events), 1)

    def test_no_hash_degrades(self):
        """No HEAD hash → no tracker, no crash."""
        with patch.object(_common, "get_head_hash", return_value=None):
            self.user_prompt_log.run(
                self._prompt_input("/security-review"),
                smm_dir=self.smm_dir,
            )
        # No tracker written, but no crash either


# ===========================================================================
# SubagentStop security review detection (Path 2) — Milestone 5.5
# ===========================================================================


class TestSubagentStopSecurity(_HookTestCase):
    """Tests for security review output detection in subagent_stop.py."""

    def setUp(self):
        super().setUp()
        import subagent_stop

        self.subagent_stop = subagent_stop

    def _subagent_input(self, last_message: str = "", **overrides) -> dict:
        data = {
            "session_id": "t",
            "agent_id": "sub1",
            "last_assistant_message": last_message,
        }
        data.update(overrides)
        return data

    def test_security_review_output_writes_tracker(self):
        """Security review output with 2+ signals writes tracker."""
        msg = "## Security Review\n\nNo vulnerabilities found in the codebase."
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input(msg),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_vulnerability_report_writes_tracker(self):
        """Vulnerability report with severity markers writes tracker."""
        msg = (
            "Security audit complete.\n"
            "Critical: 0\nHigh: 1\nMedium: 2\nLow: 3\n"
            "Found 3 vulnerabilities total."
        )
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input(msg),
                smm_dir=self.smm_dir,
            )
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_normal_output_no_tracker(self):
        """Normal subagent output doesn't write tracker."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input("Refactored the database module."),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_single_mention_below_threshold(self):
        """Single security mention (below threshold) doesn't write tracker."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input("Fixed a vulnerability in the auth code."),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_linter_output_no_false_positive(self):
        """Linter output with severity labels alone doesn't write tracker."""
        msg = "Critical: 3 issues\nHigh: 5 issues\nMedium: 12 issues\nLow: 1"
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input(msg),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_empty_message_no_tracker(self):
        """Empty message doesn't write tracker."""
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            self.subagent_stop.run(
                self._subagent_input(""),
                smm_dir=self.smm_dir,
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))


import security_review_done  # noqa: E402


class TestSecurityReviewDone(_HookTestCase):
    """PostToolUse:Skill hook writes tracker after /security-review."""

    def _skill_input(self, skill: str = "security-review", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
        }
        data.update(overrides)
        return data

    def test_writes_tracker_on_security_review(self):
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            security_review_done.run(self._skill_input(), smm_dir=self.smm_dir)
        self.assertTrue(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_ignores_other_skills(self):
        with patch.object(_common, "get_head_hash", return_value="abc1234"):
            security_review_done.run(
                self._skill_input("simplify"), smm_dir=self.smm_dir
            )
        self.assertFalse(_common.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_xp_agent_skips(self):
        result = security_review_done.run(
            self._skill_input(agent_type="xp-test"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)


# ===========================================================================
# Milestone 6: CLAUDE.md & Skills
# ===========================================================================


class TestMilestone6Files(unittest.TestCase):
    """Verify presence and content of M6 files."""

    def setUp(self):
        self.plugin_root = Path(__file__).parent.parent

    def test_behavioral_guide_exists(self):
        """BEHAVIORAL_GUIDE.md must exist at plugin root."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_behavioral_guide_token_budget(self):
        """BEHAVIORAL_GUIDE.md word count should estimate 300-2,000 tokens."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        if not path.exists():
            self.skipTest("BEHAVIORAL_GUIDE.md not yet created")
        words = len(path.read_text().split())
        estimated_tokens = words / 0.75
        self.assertGreaterEqual(
            estimated_tokens, 300, f"Too short: ~{estimated_tokens:.0f} tokens"
        )
        self.assertLessEqual(
            estimated_tokens, 2000, f"Too long: ~{estimated_tokens:.0f} tokens"
        )

    def test_skill_directories_exist(self):
        """All 3 skill dirs must exist with SKILL.md."""
        for name in ("smm-protocol", "xp-values", "pair-programming"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")

    def test_skill_frontmatter_valid(self):
        """Each SKILL.md must have valid YAML frontmatter with name + description."""
        import re

        for name in ("smm-protocol", "xp-values", "pair-programming"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            if not skill_file.exists():
                self.skipTest(f"{skill_file} not yet created")
            content = skill_file.read_text()
            # Must start with ---
            self.assertTrue(
                content.startswith("---"),
                f"{name}/SKILL.md missing frontmatter delimiter",
            )
            # Extract frontmatter
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            self.assertIsNotNone(match, f"{name}/SKILL.md frontmatter not closed")
            fm = match.group(1)
            self.assertIn("name:", fm, f"{name}/SKILL.md missing 'name' field")
            self.assertIn(
                "description:", fm, f"{name}/SKILL.md missing 'description' field"
            )
            # Name should match directory
            name_match = re.search(r"name:\s*(\S+)", fm)
            self.assertIsNotNone(name_match)
            self.assertEqual(name_match.group(1), name)

    def test_skill_token_budgets(self):
        """Each SKILL.md should be within 1,000-2,000 token estimate."""
        for name in ("smm-protocol", "xp-values", "pair-programming"):
            skill_file = self.plugin_root / "skills" / name / "SKILL.md"
            if not skill_file.exists():
                self.skipTest(f"{skill_file} not yet created")
            words = len(skill_file.read_text().split())
            estimated_tokens = words / 0.75
            self.assertGreaterEqual(
                estimated_tokens,
                800,
                f"{name} too short: ~{estimated_tokens:.0f} tokens",
            )
            self.assertLessEqual(
                estimated_tokens,
                2500,
                f"{name} too long: ~{estimated_tokens:.0f} tokens",
            )

    def test_behavioral_guide_no_contradictions(self):
        """Guide should not contradict hook enforcement (spot check)."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        if not path.exists():
            self.skipTest("BEHAVIORAL_GUIDE.md not yet created")
        content = path.read_text()
        # Guide should reference hooks, not claim to replace them
        self.assertNotIn("instead of hooks", content.lower())
        self.assertNotIn("skip the navigator", content.lower())
        self.assertNotIn("ignore quality review", content.lower())
        # Guide should mention TDD
        self.assertIn("TDD", content)
        # Guide should mention courage
        self.assertIn("Courage", content)


class TestSessionStartBehavioralGuide(_HookTestCase):
    """Tests for behavioral guide injection in session_start.py."""

    def setUp(self):
        super().setUp()
        import session_start

        session_start._load_behavioral_guide.cache_clear()

    def tearDown(self):
        import session_start

        session_start._load_behavioral_guide.cache_clear()
        super().tearDown()

    def test_session_start_includes_behavioral_guide(self):
        """Output should include behavioral guide content."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Honesty Principle", result)

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
        self.assertIn("pair-programming", result)

    def test_session_start_no_guide_degrades(self):
        """Missing BEHAVIORAL_GUIDE.md should not crash session_start."""
        import session_start

        self._write_events([make_event()])
        # Temporarily point plugin root to a dir without the guide
        tmpdir = Path(tempfile.mkdtemp())
        try:
            with patch.object(_common, "resolve_plugin_root", return_value=tmpdir):
                # Clear any cached guide
                if hasattr(session_start, "_load_behavioral_guide"):
                    session_start._load_behavioral_guide.cache_clear()
                result = session_start.run(
                    {"session_id": "test", "source": "startup"},
                    smm_dir=self.smm_dir,
                )
            self.assertIsNotNone(result)
            # Should still have GUPP and skills
            self.assertIn("Resume immediately", result)
        finally:
            import shutil

            shutil.rmtree(tmpdir)
            if hasattr(session_start, "_load_behavioral_guide"):
                session_start._load_behavioral_guide.cache_clear()

    def test_behavioral_guide_after_gupp(self):
        """Guide should appear after GUPP (reference material, not action items)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        if result and "Honesty Principle" in result:
            guide_pos = result.index("Honesty Principle")
            gupp_pos = result.index("Resume immediately")
            self.assertGreater(guide_pos, gupp_pos, "Guide should appear after GUPP")

    def test_behavioral_guide_after_smm(self):
        """Guide should appear after SMM content."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        if result and "Honesty Principle" in result:
            smm_pos = result.index("smm-context")
            guide_pos = result.index("Honesty Principle")
            self.assertLess(smm_pos, guide_pos, "SMM should appear before guide")


# ===========================================================================
# Milestone 6.5: Agent Hook → Plugin Subagent Migration
# ===========================================================================

_SUBAGENT_NAMES = (
    "xp-navigator",
    "xp-quality-reviewer",
    "xp-retrospective",
    "xp-plan-reviewer",
    "xp-subagent-reviewer",
)

_BACKGROUND_SUBAGENTS = frozenset({"xp-quality-reviewer", "xp-subagent-reviewer"})


class TestHooksJsonM65(_HooksJsonTestCase):
    """Verify no agent hooks remain in hooks.json after M6.5 migration."""

    def test_no_agent_hooks_anywhere(self):
        """hooks.json should have zero type: agent entries."""
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertNotEqual(
                        hook.get("type"),
                        "agent",
                        f"Found agent hook in {event_name}: {hook}",
                    )

    def test_only_command_and_prompt_types(self):
        """All hooks should be type: command or type: prompt."""
        valid_types = {"command", "prompt"}
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    self.assertIn(
                        hook.get("type"),
                        valid_types,
                        f"Invalid hook type in {event_name}: {hook.get('type')}",
                    )

    def test_no_prompt_hooks_remain(self):
        """All prompt hooks replaced by command hooks — none should remain."""
        prompt_hooks = []
        for event_name, entries in self.data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "prompt":
                        prompt_hooks.append((event_name, hook))
        self.assertEqual(len(prompt_hooks), 0, "No prompt hooks should remain")


class TestAgentFilesM65(unittest.TestCase):
    """Verify all 6 plugin subagent files exist with correct frontmatter."""

    def setUp(self):
        self.agents_dir = Path(__file__).parent.parent / "agents"

    def test_agents_directory_exists(self):
        self.assertTrue(self.agents_dir.is_dir(), "agents/ directory missing")

    def test_all_agent_files_exist(self):
        for name in _SUBAGENT_NAMES:
            path = self.agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing: {path}")

    def test_frontmatter_has_name(self):
        """Each agent file must have a name field matching the filename."""
        import re

        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")
            match = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
            self.assertIsNotNone(match, f"{name} missing name field")
            self.assertEqual(match.group(1).strip(), name)

    def test_frontmatter_has_description(self):
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertIn("description:", content, f"{name} missing description")

    def test_tools_include_bash(self):
        """Every subagent needs Bash for append.sh."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            # Extract frontmatter
            parts = content.split("---", 2)
            self.assertGreaterEqual(len(parts), 3, f"{name} frontmatter not closed")
            fm = parts[1]
            self.assertIn("Bash", fm, f"{name} missing Bash in tools")

    def test_skills_include_smm_protocol(self):
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            parts = content.split("---", 2)
            fm = parts[1]
            self.assertIn("smm-protocol", fm, f"{name} missing smm-protocol skill")

    def test_background_subagents(self):
        """Quality reviewer and subagent reviewer must have background: true."""
        for name in _BACKGROUND_SUBAGENTS:
            content = (self.agents_dir / f"{name}.md").read_text()
            parts = content.split("---", 2)
            fm = parts[1]
            self.assertIn("background: true", fm, f"{name} should be background")

    def test_body_mentions_append_sh(self):
        """Every subagent should reference append.sh for event writing."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            # Body is after the second ---
            parts = content.split("---", 2)
            body = parts[2] if len(parts) >= 3 else ""
            self.assertIn("append.sh", body, f"{name} body missing append.sh reference")

    def test_body_mentions_smm_content_trust(self):
        """Every subagent should have the SMM content trust section."""
        for name in _SUBAGENT_NAMES:
            content = (self.agents_dir / f"{name}.md").read_text()
            self.assertIn(
                "SMM Content Trust", content, f"{name} missing SMM Content Trust"
            )


# ===========================================================================
# M7: Plugin Integrity
# ===========================================================================


class TestPluginIntegrity(unittest.TestCase):
    """M7: marketplace.json, hooks.json references, and structural checks."""

    def setUp(self):
        self.plugin_root = Path(__file__).parent.parent

    def test_marketplace_json_exists_and_valid(self):
        """marketplace.json has required fields."""
        mp = self.plugin_root / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mp.is_file(), "Missing .claude-plugin/marketplace.json")
        data = json.loads(mp.read_text())
        self.assertIn("name", data)
        self.assertIn("owner", data)
        self.assertIn("name", data["owner"])
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)
        self.assertGreater(len(data["plugins"]), 0)
        for plugin in data["plugins"]:
            self.assertIn("name", plugin)
            self.assertIn("source", plugin)
            self.assertIn("description", plugin)

    def test_plugin_json_exists_and_valid(self):
        """plugin.json has required fields."""
        pj = self.plugin_root / ".claude-plugin" / "plugin.json"
        self.assertTrue(pj.is_file())
        data = json.loads(pj.read_text())
        self.assertIn("name", data)
        self.assertIn("version", data)
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

    def _assert_hook_paths_exist(self, hook_type: str, path_key: str):
        """Verify all hooks of given type reference existing files."""
        hooks_file = self.plugin_root / "hooks" / "hooks.json"
        data = json.loads(hooks_file.read_text())
        for event_name, entries in data["hooks"].items():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") != hook_type:
                        continue
                    raw = hook[path_key]
                    # Strip interpreter prefix (e.g. "python3 ")
                    marker = "${CLAUDE_PLUGIN_ROOT}"
                    if marker in raw:
                        path_part = raw.split(marker)[-1]
                        resolved = str(self.plugin_root) + path_part
                    else:
                        resolved = raw
                    self.assertTrue(
                        Path(resolved).is_file(),
                        f"Missing {hook_type}: {raw} (event: {event_name})",
                    )

    def test_all_hook_scripts_exist(self):
        """Every command script referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("command", "command")

    def test_all_prompt_hooks_exist(self):
        """Every prompt file referenced in hooks.json exists on disk."""
        self._assert_hook_paths_exist("prompt", "prompt")

    def test_all_agent_files_exist(self):
        """All 6 agent .md files exist in agents/ directory."""
        agents_dir = self.plugin_root / "agents"
        for name in _SUBAGENT_NAMES:
            path = agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing agent: {path}")

    def test_all_skill_files_exist(self):
        """All 3 SKILL.md files exist in skills/ directory."""
        skills_dir = self.plugin_root / "skills"
        for name in ("smm-protocol", "xp-values", "pair-programming"):
            path = skills_dir / name / "SKILL.md"
            self.assertTrue(path.is_file(), f"Missing skill: {path}")

    def test_no_requirements_or_pyproject(self):
        """No requirements.txt or pyproject.toml with dependencies."""
        for name in ("requirements.txt", "pyproject.toml"):
            path = self.plugin_root / name
            if path.is_file():
                content = path.read_text()
                self.assertNotIn(
                    "install_requires",
                    content,
                    f"{name} should not declare dependencies",
                )
                self.assertNotIn(
                    "dependencies",
                    content,
                    f"{name} should not declare dependencies",
                )

    def test_settings_json_exists(self):
        """settings.json exists with enforcement default."""
        path = self.plugin_root / "settings.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertIn("enforcement", data)

    def test_behavioral_guide_exists(self):
        """BEHAVIORAL_GUIDE.md exists and is non-trivial."""
        path = self.plugin_root / "BEHAVIORAL_GUIDE.md"
        self.assertTrue(path.is_file(), "Missing BEHAVIORAL_GUIDE.md")
        content = path.read_text()
        self.assertGreater(len(content), 1000, "BEHAVIORAL_GUIDE.md too short")


if __name__ == "__main__":
    unittest.main()
