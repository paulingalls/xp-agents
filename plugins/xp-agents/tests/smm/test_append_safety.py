#!/usr/bin/env python3
"""Tests for SMM append safety, concurrency, and validation.

Split from test_append.py — covers TestAnsiStripping, TestLockTimeout,
TestConcurrentWrites, TestAgentIdValidation, TestSmmDirValidation,
TestSymlinkProtection, TestJsonSizeLimit.
"""

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from _lock_helpers import briefly_held_lock, held_events_lock
from conftest import _SMMTestCase, _TempRepoTestCase, make_event


class TestAnsiStripping(unittest.TestCase):
    """Test that ANSI escape codes are stripped from event content at write time."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        (self.smm_dir / "events.jsonl").touch()
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        shutil.rmtree(self.smm_dir)

    def test_ansi_stripped_from_content(self):
        """ANSI escape codes should be removed from content field."""
        event = {
            "id": "test-id",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "concern",
            "agent_id": "main",
            "content": "\x1b[31mError:\x1b[0m something \x1b[1;32mfailed\x1b[0m",
            "schema_version": 1,
        }
        _append_impl.append_event(self.smm_dir, event)
        line = (self.smm_dir / "events.jsonl").read_text().strip()
        written = json.loads(line)
        self.assertEqual(written["content"], "Error: something failed")
        self.assertNotIn("\x1b", written["content"])

    def test_content_without_ansi_unchanged(self):
        """Content without ANSI codes should pass through unchanged."""
        event = {
            "id": "test-id-2",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "status",
            "agent_id": "main",
            "content": "Normal text without escapes",
            "working_on": ["app.py"],
            "schema_version": 1,
        }
        _append_impl.append_event(self.smm_dir, event)
        line = (self.smm_dir / "events.jsonl").read_text().strip()
        written = json.loads(line)
        self.assertEqual(written["content"], "Normal text without escapes")


class TestLockTimeout(_SMMTestCase):
    """Test that lock timeout raises instead of degrading."""

    def test_append_fails_on_lock_timeout(self):
        """If the lock can't be acquired, append should raise, not silently continue."""
        event = make_event(
            "customer_input", agent_id="main", content="test", id="abc123abc123"
        )

        with (
            held_events_lock(self.smm_dir),
            self.assertRaises(_append_impl.LockTimeoutError),
        ):
            _append_impl.append_event(self.smm_dir, event)
        self.assertEqual(self.events_file.read_text(), "")


class TestConcurrentWrites(_TempRepoTestCase):
    """Test atomic append under concurrent load."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def test_20_concurrent_writes(self):
        events_file = self.smm_dir / "events.jsonl"
        events_file.write_text("")

        def do_append(i: int) -> int:
            r = self._run_append(
                "--type",
                "status",
                "--agent",
                f"test-{i}",
                "--content",
                f"concurrent {i}",
                "--working-on",
                '["f.py"]',
            )
            return r.returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(do_append, i) for i in range(1, 21)]
            codes = [f.result() for f in futures]

        self.assertTrue(all(c == 0 for c in codes), f"Some appends failed: {codes}")

        lines = events_file.read_text().strip().split("\n")
        self.assertEqual(len(lines), 20, f"Expected 20 lines, got {len(lines)}")

        # All valid JSON
        events = []
        for i, line in enumerate(lines, 1):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON on line {i}")

        # All unique agent_ids
        agents = {e["agent_id"] for e in events}
        self.assertEqual(
            len(agents), 20, f"Expected 20 unique agents, got {len(agents)}"
        )


class TestLockBudgetTolerance(_SMMTestCase):
    """Flock budget must outlast brief contention from concurrent hooks.

    The original 2-second budget caused silent drops in sprint-040 — a single
    slow writer could starve every parallel async PostToolUse hook racing for
    events.lock. The bumped 10-second budget absorbs realistic contention
    while still bounding hang time. Tests patch the budget down (1-2 s) for
    speed; the production setting remains 10 s.
    """

    def test_append_event_succeeds_when_lock_released_within_budget(self):
        """A flock held briefly should clear the configured budget without
        raising LockTimeoutError. The assertion is "budget outlasts hold",
        not "wait the full hold"."""
        event = make_event(
            "customer_input", agent_id="main", content="test", id="def456def456"
        )
        with briefly_held_lock(self.smm_dir):
            _append_impl.append_event(self.smm_dir, event)
        self.assertIn("def456def456", self.events_file.read_text())


class TestAgentIdValidation(unittest.TestCase):
    """Tests for _append_impl._validate_agent_id allowlist."""

    def test_accepts_simple_name(self):
        _append_impl._validate_agent_id("main")

    def test_accepts_hyphenated(self):
        _append_impl._validate_agent_id("xp-housekeeper")

    def test_accepts_colon_separator(self):
        _append_impl._validate_agent_id("xp-quality:reviewer")

    def test_accepts_underscore(self):
        _append_impl._validate_agent_id("test_agent")

    def test_accepts_digits(self):
        _append_impl._validate_agent_id("agent123")

    def test_rejects_semicolon(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent;rm -rf")

    def test_rejects_backtick(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent`cmd`")

    def test_rejects_pipe(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent|cat")

    def test_rejects_dollar(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent$HOME")

    def test_rejects_space(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent name")

    def test_rejects_slash(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("../escape")

    def test_rejects_null(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("agent\x00id")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _append_impl._validate_agent_id("")


class TestSmmDirValidation(unittest.TestCase):
    """Tests for SMM directory ownership validation."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.smm_dir.exists():
            self.smm_dir.chmod(0o700)
            shutil.rmtree(self.smm_dir)

    def test_rejects_nonexistent(self):
        shutil.rmtree(self.smm_dir)
        with self.assertRaises(ValueError):
            _append_impl._validate_smm_dir(self.smm_dir)

    def test_rejects_world_writable(self):
        self.smm_dir.chmod(0o777)
        with self.assertRaises(ValueError):
            _append_impl._validate_smm_dir(self.smm_dir)

    def test_accepts_valid_dir(self):
        self.smm_dir.chmod(0o700)
        _append_impl._validate_smm_dir(self.smm_dir)


class TestSymlinkProtection(unittest.TestCase):
    """Tests that symlinks at lock/event paths are rejected."""

    def setUp(self):
        self.smm_dir = Path(tempfile.mkdtemp())
        (self.smm_dir / "events.jsonl").touch()
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        shutil.rmtree(self.smm_dir)

    def test_symlink_at_lock_file_rejected(self):
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock")
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        with self.assertRaises(OSError):
            _append_impl.append_event(self.smm_dir, event)

    def test_symlink_at_events_file_rejected(self):
        events_file = self.smm_dir / "events.jsonl"
        events_file.unlink()
        events_file.symlink_to("/tmp/decoy-events")
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        with self.assertRaises(OSError):
            _append_impl.append_event(self.smm_dir, event)


class TestJsonSizeLimit(unittest.TestCase):
    """Test that oversized JSON args are rejected."""

    def test_oversized_json_rejected(self):
        huge = '["' + "x" * 70000 + '"]'
        import io
        from unittest.mock import patch

        suppress_stderr = patch("sys.stderr", new_callable=io.StringIO)
        with suppress_stderr, self.assertRaises(SystemExit) as cm:
            _append_impl.parse_json_arg(huge, "references")
        self.assertEqual(cm.exception.code, 1)

    def test_normal_json_accepted(self):
        result = _append_impl.parse_json_arg('["a","b"]', "references")
        self.assertEqual(result, ["a", "b"])


class TestResolveSmmDir(unittest.TestCase):
    """Tests for resolve_smm_dir: $SMM_DIR honoring + init.sh delegation."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_honors_smm_dir_env_var(self):
        """When $SMM_DIR is set, resolve_smm_dir returns that exact path."""
        target = self.tmpdir / "custom-smm"
        env = {
            "SMM_DIR": str(target),
            "CLAUDE_PLUGIN_DATA": str(self.tmpdir / "plugin-data"),
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = _append_impl.resolve_smm_dir()
        self.assertEqual(result, target)

    def test_empty_smm_dir_falls_through_to_derivation(self):
        """Empty SMM_DIR should not short-circuit."""
        plugin_data = self.tmpdir / "plugin-data"
        env = {"SMM_DIR": "", "CLAUDE_PLUGIN_DATA": str(plugin_data)}
        with mock.patch.dict(os.environ, env, clear=False):
            result = _append_impl.resolve_smm_dir()
        self.assertIsNotNone(result)
        self.assertTrue(
            str(result).startswith(str(plugin_data)),
            f"expected derived path under CLAUDE_PLUGIN_DATA, got {result}",
        )

    def test_returns_none_when_not_in_git_repo(self):
        """Outside a git repo, resolve_smm_dir returns None (graceful)."""
        non_git = self.tmpdir / "not-a-repo"
        non_git.mkdir()
        original_cwd = Path.cwd()
        # Wipe SMM_DIR from env and cd to a non-git dir so init.sh fails.
        env_overrides = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
        try:
            os.chdir(non_git)
            with mock.patch.dict(os.environ, env_overrides, clear=True):
                result = _append_impl.resolve_smm_dir()
        finally:
            os.chdir(original_cwd)
        self.assertIsNone(result)

    def test_delegates_to_init_sh_when_env_unset(self):
        """When SMM_DIR is unset, the returned path matches what init.sh produces."""
        plugin_data = self.tmpdir / "plugin-data"
        env_overrides = {k: v for k, v in os.environ.items() if k != "SMM_DIR"} | {
            "CLAUDE_PLUGIN_DATA": str(plugin_data)
        }

        with mock.patch.dict(os.environ, env_overrides, clear=True):
            completed = subprocess.run(
                [str(_append_impl._INIT_SH)], capture_output=True, text=True
            )
            expected = completed.stdout.strip()
            result = _append_impl.resolve_smm_dir()
        self.assertEqual(str(result), expected)


if __name__ == "__main__":
    unittest.main()
