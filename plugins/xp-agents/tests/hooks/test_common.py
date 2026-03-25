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
from conftest import _HookTestCase, make_event

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
    def test_xp_housekeeping(self):
        self.assertTrue(_common.is_xp_agent({"agent_type": "xp-housekeeping"}))

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
            expected = Path(_common.__file__).parent.parent
            self.assertEqual(result, expected)


class TestResolveGitRoot(unittest.TestCase):
    def setUp(self):
        _common._clear_git_root_cache()

    def tearDown(self):
        _common._clear_git_root_cache()

    def test_returns_root_for_git_repo(self):
        """resolve_git_root returns the repo root when cwd is inside a git repo."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            result = _common.resolve_git_root(tmpdir)
            # realpath handles /private/tmp vs /tmp on macOS
            self.assertEqual(os.path.realpath(result), os.path.realpath(tmpdir))

    def test_returns_none_for_non_repo(self):
        """resolve_git_root returns None when cwd is not in a git repo."""
        result = _common.resolve_git_root("/")
        self.assertIsNone(result)

    def test_caches_per_cwd(self):
        """resolve_git_root caches results per cwd."""
        _common.resolve_git_root("/")
        _common.resolve_git_root("/tmp")
        self.assertIn("/", _common._git_root_cache)
        self.assertIn("/tmp", _common._git_root_cache)

    def test_clear_cache(self):
        """_clear_git_root_cache empties the cache."""
        _common.resolve_git_root("/")
        _common._clear_git_root_cache()
        self.assertEqual(len(_common._git_root_cache), 0)


class TestNormalizePath(unittest.TestCase):
    def setUp(self):
        _common._clear_git_root_cache()

    def tearDown(self):
        _common._clear_git_root_cache()

    def test_absolute_outside_repo_unchanged(self):
        """Paths outside any git repo stay absolute."""
        result = _common.normalize_path("/home/user/src/app.ts", "/tmp")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_relative_outside_repo_resolved_to_absolute(self):
        """Relative paths outside any git repo resolve to absolute."""
        result = _common.normalize_path("src/app.ts", "/home/user")
        self.assertEqual(result, "/home/user/src/app.ts")

    def test_dotdot_resolved(self):
        result = _common.normalize_path("../app.ts", "/home/user/src")
        self.assertEqual(result, "/home/user/app.ts")

    def test_returns_relative_inside_git_repo(self):
        """Inside a git repo, normalize_path strips the repo root."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            # Create a file so realpath resolves it
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()

            result = _common.normalize_path("src/app.ts", tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_absolute_input_inside_repo_returns_relative(self):
        """Absolute path input inside a repo is stripped to relative."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()

            abs_path = str(src_dir / "app.ts")
            result = _common.normalize_path(abs_path, tmpdir)
            self.assertEqual(result, "src/app.ts")

    def test_old_absolute_events_normalize_to_relative(self):
        """Old absolute paths from events converge to same relative form."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", tmpdir], capture_output=True, check=True)
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()
            (src_dir / "app.ts").touch()

            # Both absolute and relative inputs produce the same result
            abs_result = _common.normalize_path(str(src_dir / "app.ts"), tmpdir)
            rel_result = _common.normalize_path("src/app.ts", tmpdir)
            self.assertEqual(abs_result, rel_result)
            self.assertEqual(abs_result, "src/app.ts")


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


if __name__ == "__main__":
    unittest.main()
