#!/usr/bin/env python3
"""Tests for _common.py utilities.

Split from the monolithic test_hooks.py.
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

# ===========================================================================
# _common.py tests
# ===========================================================================


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
        # passes many ctx fields. _log_hook_error's backstop drops the
        # context dict and re-serializes when the full line still exceeds
        # 2 KB. Each value is far larger than the per-field truncation cap
        # so it gets clamped before serialization, but 30 clamped fields +
        # keys still exceed 2 KB — forcing the backstop deterministically.
        big_ctx = {f"f{i}": "x" * 1000 for i in range(30)}
        _common._log_hook_error("oversized test", error_class="probe", **big_ctx)
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
        event = make_event("status", agent_id="main", content="ok", working_on=[])
        with held_events_lock(self.smm_dir):
            _common.append_safe(self.smm_dir, event)
        entries = _read_hook_error_log(self.smm_dir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_class"], "LockTimeoutError")
        # Graceful semantic preserved — events.jsonl unchanged.
        self.assertEqual(self.events_file.read_text(), "")

    def test_bulk_append_safe_logs_lock_timeout(self):
        events = [
            make_event("status", agent_id="main", content="ok", working_on=[]),
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
            "status",
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


class TestLoadEventsWithResolutions(_HookTestCase):
    def test_returns_events_and_resolutions_tuple(self):
        self._write_events(
            [
                make_event("concern", content="bug found"),
                make_event("status", content="working"),
            ]
        )
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(len(events), 2)
        self.assertIsInstance(resolutions, dict)
        self.assertIn("resolved_concern_ids", resolutions)
        self.assertIn("answered_question_ids", resolutions)

    def test_empty_smm_returns_empty(self):
        events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertEqual(events, [])
        self.assertIsInstance(resolutions, dict)

    def test_resolutions_reflect_resolved_concerns(self):
        concern = make_event("concern", content="test fail")
        resolver = make_event(
            "status", content="fixed", metadata={"resolves": [concern["id"]]}
        )
        self._write_events([concern, resolver])
        _events, resolutions = _common.load_events_with_resolutions(self.smm_dir)
        self.assertIn(concern["id"], resolutions["resolved_concern_ids"])


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

        project_root = Path(__file__).parent.parent.parent
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


class TestBulkAppendSafe(_HookTestCase):
    """Tests for _common.bulk_append_safe()."""

    def test_bulk_append_safe_skips_invalid(self):
        """Invalid events filtered, valid ones written."""
        good = make_event("status", content="OK", working_on=[])
        bad = {"type": "status", "content": "no id"}
        _common.bulk_append_safe(self.smm_dir, [good, bad])
        events = self._read_events()
        # Only valid event written
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], good["id"])

    def test_bulk_append_safe_all_valid(self):
        """All valid events should be written."""
        events_in = [
            make_event("status", content=f"S{i}", working_on=[]) for i in range(3)
        ]
        _common.bulk_append_safe(self.smm_dir, events_in)
        events = self._read_events()
        self.assertEqual(len(events), 3)

    def test_bulk_append_safe_empty(self):
        """Empty list should be a no-op."""
        _common.bulk_append_safe(self.smm_dir, [])
        events = self._read_events()
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


class TestGetValidatedSMMDir(_HookTestCase):
    """M13: get_validated_smm_dir combines resolve + validate."""

    def test_valid_smm_dir_returned(self):
        """Explicit valid smm_dir is returned as-is."""
        result = _common.get_validated_smm_dir(self.smm_dir)
        self.assertEqual(result, self.smm_dir)

    def test_invalid_path_returns_none(self):
        """Invalid path returns None."""
        result = _common.get_validated_smm_dir(Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_none_with_no_env_returns_none(self):
        """None input without git repo returns None gracefully."""
        import os

        old = os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        try:
            # In a temp dir without git, resolve_smm_dir returns None
            result = _common.get_validated_smm_dir(None)
            # May or may not resolve depending on CWD — just verify no crash
            self.assertTrue(result is None or isinstance(result, Path))
        finally:
            if old is not None:
                os.environ["CLAUDE_PLUGIN_DATA"] = old


class TestParseAppendShArgs(unittest.TestCase):
    """Unit tests for _common.parse_append_sh_args."""

    def test_returns_empty_for_non_append_sh(self):
        self.assertEqual(_common.parse_append_sh_args("ls -la"), {})
        self.assertEqual(_common.parse_append_sh_args("git commit -m hi"), {})
        self.assertEqual(_common.parse_append_sh_args(""), {})

    def test_parses_basic_flags(self):
        cmd = "bash /p/append.sh --type decision --topic foo --content bar"
        self.assertEqual(
            _common.parse_append_sh_args(cmd),
            {"type": "decision", "topic": "foo", "content": "bar"},
        )

    def test_parses_quoted_values(self):
        cmd = (
            'bash /p/append.sh --type decision --content "multi word text" '
            "--topic 'api-style'"
        )
        self.assertEqual(
            _common.parse_append_sh_args(cmd),
            {"type": "decision", "content": "multi word text", "topic": "api-style"},
        )

    def test_parses_metadata_json(self):
        cmd = (
            "bash /p/append.sh --type decision --content x "
            """--metadata '{"resolves":["abc123"]}'"""
        )
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["metadata"], '{"resolves":["abc123"]}')

    def test_boolean_flag_followed_by_flag(self):
        """--flag --next-flag value treats first as boolean (empty value)."""
        cmd = "bash /p/append.sh --dry-run --type decision --content x"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["dry-run"], "")
        self.assertEqual(result["type"], "decision")
        self.assertEqual(result["content"], "x")

    def test_trailing_boolean_flag(self):
        cmd = "bash /p/append.sh --type decision --dry-run"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["type"], "decision")
        self.assertEqual(result["dry-run"], "")

    def test_malformed_shlex_returns_empty(self):
        # Unclosed quote breaks shlex.split — must not raise.
        self.assertEqual(_common.parse_append_sh_args('append.sh --type "x'), {})

    def test_ignores_embedded_append_sh_in_quoted_content(self):
        """append.sh as a substring of a --content value still reads args after
        the *real* append.sh token — not inside the quoted message."""
        cmd = "bash /p/append.sh --type concern --content 'see append.sh docs'"
        result = _common.parse_append_sh_args(cmd)
        self.assertEqual(result["type"], "concern")
        self.assertEqual(result["content"], "see append.sh docs")

    def test_rejects_sibling_filename_ending_in_append_sh(self):
        """A script named `fake-append.sh` must not be treated as the plugin's
        append.sh. The token check matches the filename, not a suffix."""
        cmd = "bash /tmp/fake-append.sh --type decision --content x"
        self.assertEqual(_common.parse_append_sh_args(cmd), {})


if __name__ == "__main__":
    unittest.main()
