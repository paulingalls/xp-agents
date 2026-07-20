#!/usr/bin/env python3
"""Tests for lint_check.py hook.

Split from the original test_post_tool.py.

lint_check.py behavior is further split across sibling modules to stay under
the file-size cap:
  - test_lint_ruff_and_batch.py — run_ruff / run_linter_batch low-level tests
  - test_lint_registry.py — linters.py registry/table structural pins
  - test_lint_staged_gate_branches.py — staged_lint gate branch A/B/C behavior
  - test_lint_staged_gate_edge_cases.py — staged_lint gate edge cases
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lint_check
from conftest import (
    _HookTestCase,
    _LintTmpDirMixin,
    _make_write_input,
    _mock_ruff_result,
)
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_QUESTION

_WATERMARK_ID = "test-lint"

# ===========================================================================
# lint_check.py tests — Milestone 3.3
# ===========================================================================


class TestLintCheck(_LintTmpDirMixin, _HookTestCase):
    def test_no_config_skips_non_code_files(self):
        """Non-code files (md, txt, yml, etc.) should not trigger linter nudge."""
        for filename in ("README.md", "notes.txt", "config.yml", ".gitignore"):
            # Reset flag each iteration
            (self.smm_dir / ".lint-warned").unlink(missing_ok=True)
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": filename, "content": "x"},
                ),
                smm_dir=self.smm_dir,
            )
            self.assertIsNone(result, f"Should not nudge for {filename}")
            self.assertFalse(
                (self.smm_dir / ".lint-warned").exists(),
                f"Should not create .lint-warned for {filename}",
            )

    def test_no_config_nudges_for_code_files(self):
        """Code files should trigger linter nudge."""
        for filename in ("app.py", "index.js", "main.go", "lib.rs"):
            (self.smm_dir / ".lint-warned").unlink(missing_ok=True)
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": filename, "content": "x"},
                ),
                smm_dir=self.smm_dir,
            )
            self.assertIsNotNone(result, f"Should nudge for {filename}")

    def test_no_config_nudges_once(self):
        result = lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        # Should return a nudge string, not write a question event
        assert result is not None
        self.assertIn("linter", result.lower())
        # No question events written
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        questions = events_of_type(events, EVENT_TYPE_QUESTION)
        self.assertEqual(len(questions), 0)
        # Flag file should exist
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

    def test_no_config_second_time_silent(self):
        (self.smm_dir / ".lint-warned").touch()
        result = lint_check.run(
            _make_write_input(),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        questions = events_of_type(events, EVENT_TYPE_QUESTION)
        self.assertEqual(len(questions), 0)

    def test_linter_binary_missing(self):
        # ruff.toml is in self._lint_tmpdir but ruff isn't on PATH
        with patch("lint_check.shutil.which", return_value=None):
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": "src/app.py", "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0)

    def test_clean_lint_no_event(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": "src/app.py", "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0)

    def test_lint_errors_appends_concern(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout="src/app.py:1:1: E302 expected 2 blank lines",
            )
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": "src/app.py", "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0].get("severity"), "medium")

    def test_lint_concern_not_duplicated(self):
        """Second lint run for same file should not append duplicate concern."""
        mock_result = _mock_ruff_result(
            returncode=1,
            stdout="src/app.py:1:1: E302 expected 2 blank lines",
        )
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", return_value=mock_result),
        ):
            inp = _make_write_input(
                tool_input={"file_path": "src/app.py", "content": "x"},
                cwd=str(self._lint_tmpdir),
            )
            lint_check.run(inp, smm_dir=self.smm_dir)
            lint_check.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1, "Duplicate lint concern appended")

    def test_lint_timeout(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.run_linter", return_value=None),
        ):
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": "src/app.py", "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0)

    def test_xp_agent_skips(self):
        lint_check.run(
            _make_write_input(agent_type="xp-housekeeper"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        lint_check.run(
            _make_write_input(),
            smm_dir=fake_dir,
        )

    def test_ruff_skips_json_file(self):
        """ruff should not run against .json files — they are not Python."""
        with patch("lint_check.shutil.which", return_value="/usr/bin/ruff"):
            result = lint_check.run_linter(
                "ruff", str(self._lint_tmpdir / "hooks.json")
            )
        self.assertIsNone(result)

    def test_ruff_runs_on_python_file(self):
        """ruff should still run on .py files."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            result = lint_check.run_linter("ruff", str(self._lint_tmpdir / "app.py"))
        self.assertIsNone(result)  # clean — no errors
        mock_run.assert_called_once()

    def test_run_linter_passes_cwd(self):
        """run_linter should pass cwd to subprocess so relative paths resolve."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter("ruff", "src/app.py", cwd="/projects/myapp")
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("cwd"), "/projects/myapp")

    def test_detect_skips_linter_for_wrong_extension(self):
        """detect_linter_config should skip eslint for .py files."""
        (self._lint_tmpdir / "eslint.config.js").touch()
        result = lint_check.detect_linter_config(
            str(self._lint_tmpdir),
            str(self._lint_tmpdir),
            file_path="src/app.py",
        )
        assert result is not None
        self.assertEqual(result[0], "ruff")

    def test_detect_returns_eslint_for_js_files(self):
        """detect_linter_config should return eslint for .js files."""
        (self._lint_tmpdir / "eslint.config.js").touch()
        result = lint_check.detect_linter_config(
            str(self._lint_tmpdir),
            str(self._lint_tmpdir),
            file_path="src/app.js",
        )
        assert result is not None
        self.assertEqual(result[0], "eslint")

    def test_detect_walks_from_file_directory(self):
        """detect_linter_config should start from the file's dir, not cwd."""
        tmpdir = Path(tempfile.mkdtemp())
        # eslint at root, ruff in subdirectory
        (tmpdir / "eslint.config.js").touch()
        subdir = tmpdir / "apps" / "agent"
        subdir.mkdir(parents=True)
        pyproject = subdir / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\ntarget-version = 'py311'\n")
        try:
            # File is in apps/agent/ — should find ruff there, not eslint at root
            result = lint_check.detect_linter_config(
                str(tmpdir), str(tmpdir), file_path="apps/agent/foo.py"
            )
            assert result is not None
            self.assertEqual(result[0], "ruff")
        finally:
            import shutil as sh

            sh.rmtree(tmpdir)

    def test_lint_errors_return_context(self):
        """Lint errors should return additionalContext string."""
        (self.smm_dir / ".lint-warned").touch()  # suppress no-config warning
        target = self._lint_tmpdir / "app.py"
        target.write_text("import os\n")
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout="app.py:1:1: F841 unused variable",
            )
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("Lint errors", result)
        self.assertIn("F841", result)

    def test_clean_lint_returns_none(self):
        """Clean lint should return None (no additionalContext)."""
        target = self._lint_tmpdir / "app.py"
        target.write_text("x = 1\n")
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
        ):
            mock_run.return_value = _mock_ruff_result()
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_run_invokes_linter_from_config_dir(self):
        """In a monorepo, the linter runs with cwd=the config file's directory,
        not git root, so `npx eslint` resolves the subpackage's node_modules
        binary and eslint v9 flat config resolves from that dir. The file arg
        is passed relative to the config dir, not git-root-relative.
        """
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subpkg = repo / "apps" / "mobile"
        (subpkg / "src").mkdir(parents=True)
        (subpkg / "eslint.config.mjs").touch()
        target = subpkg / "src" / "foo.ts"
        target.write_text("const x = 1\n")
        (self.smm_dir / ".lint-warned").touch()  # suppress no-config nudge
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.worktree.resolve_git_root", return_value=str(repo)),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()  # clean
            lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(repo),
                ),
                smm_dir=self.smm_dir,
            )
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("cwd"), os.path.realpath(str(subpkg)))
        cmd = mock_run.call_args[0][0]
        self.assertIn("src/foo.ts", cmd)
        self.assertNotIn("apps/mobile/src/foo.ts", " ".join(cmd))


# ===========================================================================
# Story-007: ruff F401/F811 deferred from edit-time to staging-time
# ===========================================================================


class TestLintEditContextFilters(_LintTmpDirMixin, _HookTestCase):
    """End-to-end: lint_check.run() is the 'edit' context entry point.

    A file whose only ruff finding is F401 must NOT raise a concern and
    must NOT return additionalContext — F401 enforcement is deferred to
    the commit-gate staging check in pre_tool_bash.
    """

    def test_F401_only_returns_no_concern_at_edit_time(self):
        target = self._lint_tmpdir / "app.py"
        target.write_text("import os\n")
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: F401 [*] `os` imported but unused\nFound 1 error.\n"
                ),
            )
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result, "F401 must not surface at edit time")
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 0, "F401 must not raise concern at edit time")

    def test_non_F401_still_surfaces_at_edit_time(self):
        """E302 (non-deferred code) still creates a concern at edit time."""
        target = self._lint_tmpdir / "app.py"
        target.write_text("def f():\n    pass\n")
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
            patch("lint_check.detect_linter_config", return_value=("ruff", "")),
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=("app.py:1:1: E302 expected 2 blank lines\nFound 1 error.\n"),
            )
            result = lint_check.run(
                _make_write_input(
                    tool_input={"file_path": str(target), "content": "x"},
                    cwd=str(self._lint_tmpdir),
                ),
                smm_dir=self.smm_dir,
            )
        assert result is not None
        self.assertIn("E302", result)
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)


if __name__ == "__main__":
    unittest.main()
