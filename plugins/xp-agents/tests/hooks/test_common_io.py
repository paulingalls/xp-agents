#!/usr/bin/env python3
"""Tests for _common.py — hook I/O primitives and error-log tracing.

Split from test_common.py (pure move, no test-body edits). Covers
resolve_smm_dir, read_hook_input (+ its silent-failure error-log trace),
append_safe/bulk_append_safe error-log trace, hook_output, and is_xp_agent.
Sibling groups: persistence (test_common_persistence.py), stdlib import
policy (test_common_stdlib.py), event/arg bookkeeping (test_common_events.py).
"""

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from _lock_helpers import held_events_lock
from conftest import _HookTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_STATUS,
)


def _read_hook_error_log(smm_dir: Path) -> list[dict]:
    """Parse ${smm_dir}/hook_errors.jsonl, skipping empty lines."""
    path = smm_dir / "hook_errors.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestResolveSmmDir(unittest.TestCase):
    def test_returns_path_in_git_repo(self):
        result = _common.resolve_smm_dir()
        # We're running tests from within a git repo
        self.assertIsNotNone(result)
        self.assertTrue(str(result).endswith("/smm"))

    def test_honors_smm_dir_env_var(self):
        """resolve_smm_dir delegates — $SMM_DIR env var wins over derivation."""
        with patch.dict(os.environ, {"SMM_DIR": "/tmp/test-smm-common"}, clear=False):
            result = _common.resolve_smm_dir()
        self.assertEqual(result, Path("/tmp/test-smm-common"))

    def test_returns_none_outside_git(self):
        with patch(
            "_append_impl.subprocess.check_output", side_effect=FileNotFoundError
        ):
            # Also clear SMM_DIR so we fall through to the subprocess path
            env_without_smm = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
            with patch.dict(os.environ, env_without_smm, clear=True):
                result = _common.resolve_smm_dir()
        self.assertIsNone(result)

    def test_returns_none_on_init_sh_error(self):
        from subprocess import CalledProcessError

        with patch(
            "_append_impl.subprocess.check_output",
            side_effect=CalledProcessError(128, "bash"),
        ):
            env_without_smm = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
            with patch.dict(os.environ, env_without_smm, clear=True):
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


class TestReadHookInputErrorLogging(_HookTestCase):
    """Silent-failure paths in read_hook_input must leave a hook_errors.jsonl trace."""

    def test_invalid_json_logs_to_hook_errors_jsonl(self):
        with patch("sys.stdin", io.StringIO("not json at all")):
            with self.assertRaises(SystemExit) as cm:
                _common.read_hook_input()
            self.assertEqual(cm.exception.code, 0)
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "JSONDecodeError")

    def test_oversize_stdin_logs_to_hook_errors_jsonl(self):
        # Shrink the cap so the test allocates ~2 KB instead of 11 MB while
        # still exercising the oversize branch.
        with (
            patch.object(_common, "_MAX_STDIN_SIZE", 1024),
            patch("sys.stdin", io.StringIO("x" * 2048)),
            self.assertRaises(SystemExit) as cm,
        ):
            _common.read_hook_input()
        self.assertEqual(cm.exception.code, 0)
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "stdin_oversize")

    def test_oversized_entry_triggers_paranoid_backstop(self):
        # Per-field truncation alone can't bound total line size if a caller
        # passes many ctx fields. log_hook_error's backstop drops the
        # context dict and re-serializes when the full line still exceeds
        # 2 KB. Each value is far larger than the per-field truncation cap
        # so it gets clamped before serialization, but 30 clamped fields +
        # keys still exceed 2 KB — forcing the backstop deterministically.
        big_ctx = {f"f{i}": "x" * 1000 for i in range(30)}
        _common.log_hook_error("oversized test", error_class="probe", **big_ctx)
        path = self.smm_dir / "hook_errors.jsonl"
        line = path.read_text().splitlines()[0]
        self.assertLessEqual(
            len(line.encode("utf-8")),
            2048,
            "hook_errors.jsonl line exceeded 2 KB cap",
        )
        # Backstop dropped context; core fields preserved and JSON parseable.
        entry = json.loads(line)
        self.assertNotIn("context", entry)
        self.assertEqual(entry["error_class"], "probe")
        self.assertEqual(entry["reason"], "oversized test")


class TestAppendSafeErrorLogging(_HookTestCase):
    """append_safe / bulk_append_safe must log suppressed errors to hook_errors.jsonl.

    The original silent-suppress in `contextlib.suppress(LockTimeoutError, ValueError)`
    dropped events without a trace under flock contention or oversized payloads.
    These tests pin the loud-failure invariant: the suppressed exception still
    leaves a structured entry in ``${SMM_DIR}/hook_errors.jsonl`` so future
    regressions are visible.
    """

    def test_append_safe_logs_lock_timeout(self):
        event = make_event(
            EVENT_TYPE_STATUS, agent_id="main", content="ok", working_on=[]
        )
        with held_events_lock(self.smm_dir):
            _common.append_safe(self.smm_dir, event)
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "LockTimeoutError")
        # Graceful semantic preserved — events.jsonl unchanged.
        self.assertEqual(self.events_file.read_text(), "")

    def test_bulk_append_safe_logs_lock_timeout(self):
        events = [
            make_event(EVENT_TYPE_STATUS, agent_id="main", content="ok", working_on=[]),
        ]
        with held_events_lock(self.smm_dir):
            _common.bulk_append_safe(self.smm_dir, events)
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "LockTimeoutError")
        self.assertEqual(self.events_file.read_text(), "")

    def test_bulk_append_safe_logs_value_error_when_serialized_too_large(self):
        # working_on with a 110 KB string passes content-budget validation
        # (status content="ok" is 2 chars), but the serialized JSON exceeds the
        # 100 KB MAX_EVENT_BYTES cap inside _append_impl.bulk_append → ValueError.
        oversized = make_event(
            EVENT_TYPE_STATUS,
            agent_id="main",
            content="ok",
            working_on=["x" * 110_000],
        )
        _common.bulk_append_safe(self.smm_dir, [oversized])
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "ValueError")
        self.assertEqual(self.events_file.read_text(), "")


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
    def test_xp_housekeeping(self):
        self.assertTrue(_common.is_xp_agent({"agent_type": "xp-housekeeper"}))

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


if __name__ == "__main__":
    unittest.main()
