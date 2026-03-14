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
        self.assertIsNone(result)

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
                "plan_review",
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
# plan_review.py tests (Milestone 4)
# ===========================================================================


class TestPlanReview(_HookTestCase):
    """Unit tests for plan_review.py run() function."""

    def test_xp_agent_skips(self):
        import plan_review

        result = plan_review.run(
            {
                "session_id": "test",
                "agent_type": "xp-plan-reviewer",
                "last_assistant_message": "1. do stuff",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_graceful_no_smm(self):
        import plan_review

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = plan_review.run(
            {"session_id": "test", "last_assistant_message": "1. do stuff"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_small_plan_no_size_flag(self):
        import plan_review

        plan = "\n".join(f"{i + 1}. Step {i + 1}" for i in range(5))
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("large plan", result.lower())

    def test_large_plan_flags_size(self):
        import plan_review

        plan = "\n".join(f"{i + 1}. Step {i + 1}" for i in range(15))
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("large plan", result.lower())

    def test_missing_test_strategy_flagged(self):
        import plan_review

        plan = "1. Create feature module\n2. Add routing\n3. Deploy"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("test", result.lower())

    def test_plan_with_test_strategy_ok(self):
        import plan_review

        plan = "1. Write tests for auth\n2. Implement auth module\n3. Run test suite"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("No test/TDD strategy", result)

    def test_context_includes_plan_content(self):
        import plan_review

        plan = "1. Implement the widget\n2. Test the widget"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIn("Implement the widget", result)

    def test_context_includes_all_decisions(self):
        import plan_review

        d = make_event(
            "decision",
            topic="auth",
            content="Use JWT for auth",
            working_on=["/tmp/src/auth.py"],
        )
        self._write_events([d])
        plan = "1. Refactor auth module"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIn("Use JWT for auth", result)

    def test_missing_last_assistant_message(self):
        import plan_review

        result = plan_review.run(
            {"session_id": "test", "agent_id": "plan-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_step_counting_numbered_list(self):
        import plan_review

        plan = "1. First step\n2. Second step\n3. Third step"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIn("3 steps", result)

    def test_step_counting_bullets(self):
        import plan_review

        plan = "- First step\n- Second step\n* Third step\n* Fourth step"
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIn("4 steps", result)

    def test_appends_status_event(self):
        import plan_review

        plan = "1. Do things"
        plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("plan review" in s["content"].lower() for s in statuses))

    def test_plan_content_truncated(self):
        import plan_review

        plan = "1. Step one\n" + "x" * 6000
        result = plan_review.run(
            {
                "session_id": "test",
                "last_assistant_message": plan,
                "agent_id": "plan-1",
            },
            smm_dir=self.smm_dir,
        )
        # Context should contain truncated plan, not the full 6000+ chars
        # The plan content section should be <= 5000 chars
        self.assertIn("truncated", result.lower())


# ===========================================================================
# Prompt file tests (Milestone 4)
# ===========================================================================


class TestPromptFiles(unittest.TestCase):
    """Verify all agent hook prompt files exist and contain key content."""

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent / "prompts"

    # --- navigator.md ---

    def test_navigator_md_exists(self):
        self.assertTrue((self.prompts_dir / "navigator.md").exists())

    def test_navigator_md_contains_pair_guidance(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("pair_guidance", content)

    def test_navigator_md_references_append_sh(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("append.sh", content)

    def test_navigator_md_mentions_trivial_filter(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("trivial", content.lower())

    def test_navigator_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("xp-navigator", content)

    # --- quality_reviewer.md ---

    def test_quality_reviewer_md_exists(self):
        self.assertTrue((self.prompts_dir / "quality_reviewer.md").exists())

    def test_quality_reviewer_md_contains_concern(self):
        content = (self.prompts_dir / "quality_reviewer.md").read_text()
        self.assertIn("concern", content)

    def test_quality_reviewer_md_references_append_sh(self):
        content = (self.prompts_dir / "quality_reviewer.md").read_text()
        self.assertIn("append.sh", content)

    def test_quality_reviewer_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "quality_reviewer.md").read_text()
        self.assertIn("xp-quality-reviewer", content)

    # --- plan_reviewer.md ---

    def test_plan_reviewer_md_exists(self):
        self.assertTrue((self.prompts_dir / "plan_reviewer.md").exists())

    def test_plan_reviewer_md_contains_assumption(self):
        content = (self.prompts_dir / "plan_reviewer.md").read_text()
        self.assertIn("assumption", content)

    def test_plan_reviewer_md_contains_decision(self):
        content = (self.prompts_dir / "plan_reviewer.md").read_text()
        self.assertIn("decision", content)

    def test_plan_reviewer_md_references_append_sh(self):
        content = (self.prompts_dir / "plan_reviewer.md").read_text()
        self.assertIn("append.sh", content)

    def test_plan_reviewer_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "plan_reviewer.md").read_text()
        self.assertIn("xp-plan-reviewer", content)


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
    """Verify hooks.json has all M4 agent hook registrations."""

    # --- PreToolUse: navigator ---

    def test_pretooluse_has_write_edit_matcher(self):
        entry = self._find_matcher_entry("PreToolUse", "Write|Edit|MultiEdit")
        self.assertIsNotNone(entry, "PreToolUse Write|Edit|MultiEdit entry missing")

    def test_pretooluse_navigator_agent(self):
        entry = self._find_matcher_entry("PreToolUse", "Write|Edit|MultiEdit")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["agent_type"], "xp-navigator")
        self.assertIn("navigator.md", agents[0]["prompt"])

    # --- PostToolUse: quality_reviewer ---

    def test_posttooluse_quality_reviewer_async(self):
        entry = self._find_matcher_entry("PostToolUse", "Write|Edit|MultiEdit")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 1)
        self.assertTrue(agents[0].get("async"), "quality_reviewer should be async")
        self.assertEqual(agents[0]["agent_type"], "xp-quality-reviewer")
        self.assertIn("quality_reviewer.md", agents[0]["prompt"])

    # --- SubagentStop: plan_review + plan_reviewer ---

    def test_subagentstop_plan_matcher(self):
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        self.assertIsNotNone(entry, "SubagentStop Plan matcher entry missing")

    def test_subagentstop_plan_review_command(self):
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        commands = [h for h in entry["hooks"] if h.get("type") == "command"]
        self.assertTrue(
            any("plan_review.py" in h["command"] for h in commands),
            "plan_review.py command hook missing",
        )

    def test_subagentstop_plan_reviewer_agent(self):
        entry = self._find_matcher_entry("SubagentStop", "Plan")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["agent_type"], "xp-plan-reviewer")
        self.assertIn("plan_reviewer.md", agents[0]["prompt"])

    # --- Plugin version bump ---

    def test_plugin_version_m4(self):
        plugin_path = Path(__file__).parent.parent / ".claude-plugin" / "plugin.json"
        with open(plugin_path) as f:
            plugin = json.load(f)
        # Updated to 0.5.4 in M5.4
        self.assertEqual(plugin["version"], "0.5.4")


# ===========================================================================
# Prompt file tests (Milestone 5)
# ===========================================================================


class TestPromptFilesM5(unittest.TestCase):
    """Verify all M5 agent/prompt hook files exist and contain key content."""

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent / "prompts"

    # --- retrospective_analyst.md ---

    def test_retrospective_analyst_md_exists(self):
        self.assertTrue((self.prompts_dir / "retrospective_analyst.md").exists())

    def test_retrospective_analyst_md_contains_keep_fix_try(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn("Keep", content)
        self.assertIn("Fix", content)
        self.assertIn("Try", content)

    def test_retrospective_analyst_md_references_append_sh(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn("append.sh", content)

    def test_retrospective_analyst_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn("xp-retrospective-analyst", content)

    def test_retrospective_analyst_md_mentions_retro_input(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn(".retro-input.json", content)

    def test_retrospective_analyst_md_mentions_xp_values(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        for value in ["Honesty", "Communication", "Courage", "Simplicity", "Respect"]:
            self.assertIn(value, content)

    # --- customer_proxy.md ---

    def test_customer_proxy_md_exists(self):
        self.assertTrue((self.prompts_dir / "customer_proxy.md").exists())

    def test_customer_proxy_md_contains_ask_user_question(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("AskUserQuestion", content)

    def test_customer_proxy_md_references_append_sh(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("append.sh", content)

    def test_customer_proxy_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("xp-customer-proxy", content)

    def test_customer_proxy_md_mentions_questions(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("question", content.lower())

    # --- subagent_reviewer.md ---

    def test_subagent_reviewer_md_exists(self):
        self.assertTrue((self.prompts_dir / "subagent_reviewer.md").exists())

    def test_subagent_reviewer_md_contains_concern(self):
        content = (self.prompts_dir / "subagent_reviewer.md").read_text()
        self.assertIn("concern", content)

    def test_subagent_reviewer_md_references_append_sh(self):
        content = (self.prompts_dir / "subagent_reviewer.md").read_text()
        self.assertIn("append.sh", content)

    def test_subagent_reviewer_md_mentions_recursion_prevention(self):
        content = (self.prompts_dir / "subagent_reviewer.md").read_text()
        self.assertIn("xp-subagent-reviewer", content)

    def test_subagent_reviewer_md_mentions_transcript(self):
        content = (self.prompts_dir / "subagent_reviewer.md").read_text()
        self.assertIn("transcript", content.lower())

    # --- tdd_check.md ---

    def test_tdd_check_md_exists(self):
        self.assertTrue((self.prompts_dir / "tdd_check.md").exists())

    def test_tdd_check_md_mentions_tests(self):
        content = (self.prompts_dir / "tdd_check.md").read_text()
        self.assertIn("test", content.lower())

    def test_tdd_check_md_mentions_stop_hook_active(self):
        content = (self.prompts_dir / "tdd_check.md").read_text()
        self.assertIn("stop_hook_active", content)

    def test_tdd_check_md_mentions_block(self):
        content = (self.prompts_dir / "tdd_check.md").read_text()
        self.assertIn("block", content.lower())

    def test_tdd_check_md_uses_ok_reason_format(self):
        """Prompt hooks must use ok/reason format, not decision/block."""
        content = (self.prompts_dir / "tdd_check.md").read_text()
        self.assertIn('"ok":', content)
        self.assertIn('"reason":', content)


# ===========================================================================
# M5.3 acceptance criteria — prompt content verification
# ===========================================================================


class TestM53AcceptanceCriteria(unittest.TestCase):
    """Verify M5.3 acceptance criteria are met.

    Prompt-only behaviors are verified by checking prompt content.
    Testable behaviors are verified in their respective test classes:
    - TestPreToolUseEnforcement (ACs 1-2)
    - TestLoadEnforcementMode (AC 3)
    - TestFindDebtForFile (AC 9)
    - TestPreToolUseDebtInjection (AC 10)
    - TestPreToolUseActiveContext (AC 15)
    """

    def setUp(self):
        self.prompts_dir = Path(__file__).parent.parent / "prompts"

    # AC 1: strict blocks on decision contradictions (navigator prompt)
    def test_navigator_can_block_on_contradictions(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("block", content.lower())
        self.assertIn("contradict", content.lower())

    # AC 4: first session asks for goals
    def test_customer_proxy_goal_collection(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("Goal Collection", content)
        self.assertIn("Project Goals", content)
        self.assertIn('--type "goal"', content)

    # AC 5: customer proxy distills intents
    def test_customer_proxy_intent_distillation(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("Intent Reconciliation", content)
        self.assertIn("customer_input", content)
        self.assertIn("--intent-status", content)

    # AC 7: delivered intents by event log activity
    def test_customer_proxy_delivery_by_events(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("status", content)
        self.assertIn("decision", content)
        self.assertIn("delivered", content)

    # AC 8: ambiguous keeps intent open
    def test_customer_proxy_err_toward_open(self):
        content = (self.prompts_dir / "customer_proxy.md").read_text()
        self.assertIn("Err toward keeping intents open", content)

    # AC 10: navigator debt awareness (prompt side)
    def test_navigator_debt_awareness(self):
        content = (self.prompts_dir / "navigator.md").read_text()
        self.assertIn("Debt Awareness", content)
        self.assertIn("smm-debt-context", content)

    # AC 11: quality reviewer flags ignored debt
    def test_quality_reviewer_flags_ignored_debt(self):
        content = (self.prompts_dir / "quality_reviewer.md").read_text()
        self.assertIn('--type "debt"', content)
        self.assertIn("debt was not addressed", content)

    # AC 12: retrospective escalates aging debt
    def test_retrospective_escalates_aging_debt(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn("Escalating aging debt", content)
        self.assertIn("high-priority", content)

    # AC 13: retrospective flags plugin health anomalies
    def test_retrospective_plugin_health(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
        self.assertIn("Plugin Health", content)
        self.assertIn("session_stats", content)
        self.assertIn("pair_guidance", content)

    # AC 14: cross-session trends
    def test_retrospective_cross_session_trends(self):
        content = (self.prompts_dir / "retrospective_analyst.md").read_text()
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

    # --- SessionStart: retrospective_analyst agent ---

    def test_session_start_has_retro_analyst_agent(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        retro_agents = [
            a for a in agents if a.get("agent_type") == "xp-retrospective-analyst"
        ]
        self.assertEqual(len(retro_agents), 1)
        self.assertIn("retrospective_analyst.md", retro_agents[0]["prompt"])

    # --- SessionStart: customer_proxy agent ---

    def test_session_start_has_customer_proxy_agent(self):
        entry = self._find_matcher_entry("SessionStart", "startup|resume|compact|clear")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        proxy_agents = [a for a in agents if a.get("agent_type") == "xp-customer-proxy"]
        self.assertEqual(len(proxy_agents), 1)
        self.assertIn("customer_proxy.md", proxy_agents[0]["prompt"])

    # --- SubagentStop: subagent_reviewer agent (async) ---

    def test_subagentstop_default_has_reviewer_agent(self):
        entry = self._find_default_entry("SubagentStop")
        self.assertIsNotNone(entry, "SubagentStop default entry missing")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["agent_type"], "xp-subagent-reviewer")
        self.assertIn("subagent_reviewer.md", agents[0]["prompt"])

    def test_subagentstop_reviewer_is_async(self):
        entry = self._find_default_entry("SubagentStop")
        agents = [h for h in entry["hooks"] if h.get("type") == "agent"]
        self.assertTrue(agents[0].get("async"), "subagent_reviewer should be async")

    # --- Stop: tdd_check prompt ---

    def test_stop_hook_exists(self):
        self.assertIn("Stop", self.data["hooks"], "Stop hook section missing")

    def test_stop_hook_has_tdd_check_prompt(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        prompt_hooks = [h for h in all_hooks if h.get("type") == "prompt"]
        self.assertEqual(len(prompt_hooks), 1)
        self.assertIn("tdd_check.md", prompt_hooks[0]["prompt"])


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

    def test_stop_has_tdd_check_prompt(self):
        entries = self.data["hooks"]["Stop"]
        all_hooks = []
        for entry in entries:
            all_hooks.extend(entry.get("hooks", []))
        prompts = [h for h in all_hooks if h.get("type") == "prompt"]
        self.assertTrue(
            any("tdd_check.md" in h["prompt"] for h in prompts),
            "tdd_check.md prompt hook missing from Stop",
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
        self.assertTrue(self.pre_tool_use.is_git_push("git  push --force"))

    def test_is_git_push_negative(self):
        """is_git_push rejects non-push commands."""
        self.assertFalse(self.pre_tool_use.is_git_push("git commit -m 'test'"))
        self.assertFalse(self.pre_tool_use.is_git_push("git pull origin main"))
        self.assertFalse(self.pre_tool_use.is_git_push("git pushx"))

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
                e for e in events if e.get("type") == "security_review_requested"
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


if __name__ == "__main__":
    unittest.main()
