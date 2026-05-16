#!/usr/bin/env python3
"""Tests for lint_check.py hook.

Split from the original test_post_tool.py.
"""

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


# ===========================================================================
# Story-007: ruff F401/F811 deferred from edit-time to staging-time
# ===========================================================================


class TestRunRuffContext(_HookTestCase):
    """run_ruff is the single source of truth for ruff invocation.

    'edit' context drops F401/F811 (defer to staging — they false-positive
    mid-edit during multi-step replace_all migrations); 'staging' preserves
    them so the commit gate catches truly-unused imports.
    """

    def test_run_ruff_filters_F401_in_edit_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: F401 [*] `os` imported but unused\n"
                    "app.py:3:5: E302 expected 2 blank lines\n"
                    "Found 2 errors.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertNotIn("F401", codes)
        self.assertIn("E302", codes)

    def test_run_ruff_filters_F811_in_edit_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:5:1: F811 redefinition of unused `foo`\nFound 1 error.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertEqual(codes, [])

    def test_run_ruff_preserves_F401_in_staging_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: F401 [*] `os` imported but unused\nFound 1 error.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("F401", codes)

    def test_run_ruff_preserves_F811_in_staging_context(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:5:1: F811 redefinition of unused `foo`\nFound 1 error.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("F811", codes)

    def test_run_ruff_filtered_text_excludes_filtered_lines(self):
        """In 'edit' context, filtered output text should NOT mention F401."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: F401 [*] `os` imported but unused\n"
                    "app.py:3:5: E302 expected 2 blank lines\n"
                    "Found 2 errors.\n"
                ),
            )
            _codes, text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertNotIn("F401", text)
        self.assertIn("E302", text)

    def test_run_ruff_returns_empty_when_ruff_clean(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            codes, text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertEqual(codes, [])
        self.assertEqual(text, "")

    def test_run_ruff_returns_empty_when_binary_missing(self):
        with patch("lint_check.shutil.which", return_value=None):
            codes, text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertEqual(codes, [])
        self.assertEqual(text, "")

    def test_run_ruff_parses_multi_letter_codes(self):
        """Ruff plugin namespaces (RUF, PLR, ANN, UP, ...) use 2-3 letter
        prefixes. A single-letter regex would silently drop them — codes=[]
        flips has_errors to False and the lint error never surfaces."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: RUF059 unpacked variable\n"
                    "app.py:2:1: PLR0915 too many statements\n"
                    "app.py:3:1: UP007 use X | Y\n"
                    "Found 3 errors.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="edit")
        self.assertIn("RUF059", codes)
        self.assertIn("PLR0915", codes)
        self.assertIn("UP007", codes)

    def test_run_ruff_parses_4plus_letter_prefixes(self):
        """Block-fix (concern 56a0e138ef8e): the {1,3}-letter regex bound still
        silently drops 4+ letter ruff plugin codes (PERF, FURB, FAST, ASYNC).
        When the regex misses, codes=[] flips has_errors=False and the lint
        error vanishes at edit time — same failure class as the single-letter
        bug that was previously fixed but not widely enough."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=1,
                stdout=(
                    "app.py:1:1: PERF401 use list comprehension\n"
                    "app.py:2:1: FURB169 use isinstance not type comparison\n"
                    "app.py:3:1: ASYNC100 unnecessary trio.fail_after\n"
                    "Found 3 errors.\n"
                ),
            )
            codes, _text = lint_check.run_ruff(Path("app.py"), context="staging")
        self.assertIn("PERF401", codes)
        self.assertIn("FURB169", codes)
        self.assertIn("ASYNC100", codes)


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


# ===========================================================================
# Story-020 phase 3: run_linter_batch — single fork over multiple paths
# ===========================================================================


class TestRunLinterBatch(_HookTestCase):
    """run_linter_batch forks the linter ONCE for all paths and returns
    a {path: codes} dict. Generalizes per-file run_ruff so commit-gate
    callers can replace per-file forks with one batch invocation. Routes
    by linter_name like run_linter (ruff today; flake8/eslint/etc later
    without API change)."""

    def test_one_fork_for_multiple_paths(self):
        """Single ruff invocation regardless of how many paths are passed."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.py", "c.py"],
                context="staging",
                cwd="/tmp",
            )
        mock_run.assert_called_once()

    def test_returns_dict_mapping_paths_to_codes(self):
        """Each path → list of codes; clean files map to []."""
        stdout = (
            "a.py:1:1: F401 [*] `os` imported but unused\n"
            "c.py:5:1: E302 expected 2 blank lines\n"
            "Found 2 errors.\n"
        )
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(returncode=1, stdout=stdout)
            result = lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.py", "c.py"],
                context="staging",
                cwd="/tmp",
            )
        self.assertEqual(result["a.py"], ["F401"])
        self.assertEqual(result["b.py"], [])  # clean
        self.assertEqual(result["c.py"], ["E302"])

    def test_paths_passed_to_subprocess(self):
        """All paths appear after `--` in the ruff command line."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.py"],
                context="staging",
                cwd="/tmp",
            )
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("--", cmd)
        sep = cmd.index("--")
        self.assertEqual(cmd[sep + 1 :], ["a.py", "b.py"])

    def test_edit_context_filters_F401_F811(self):
        """Edit context strips deferred codes per file (mirrors run_ruff)."""
        stdout = (
            "a.py:1:1: F401 [*] `os` imported but unused\n"
            "a.py:5:1: E302 expected 2 blank lines\n"
            "b.py:1:1: F811 redefinition of unused `foo`\n"
            "Found 3 errors.\n"
        )
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(returncode=1, stdout=stdout)
            result = lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.py"],
                context="edit",
                cwd="/tmp",
            )
        self.assertEqual(result["a.py"], ["E302"])  # F401 stripped
        self.assertEqual(result["b.py"], [])  # F811 stripped

    def test_empty_paths_returns_empty_dict_no_fork(self):
        """No paths → no fork, empty dict."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            result = lint_check.run_linter_batch(
                "ruff", [], context="staging", cwd="/tmp"
            )
        mock_run.assert_not_called()
        self.assertEqual(result, {})

    def test_skips_files_with_wrong_extension(self):
        """ruff only knows .py/.pyi/.ipynb — non-Python paths skipped, not forked on."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            result = lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.json", "c.md"],
                context="staging",
                cwd="/tmp",
            )
        # Only a.py forwarded to ruff; b.json/c.md absent from result
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        sep = cmd.index("--")
        self.assertEqual(cmd[sep + 1 :], ["a.py"])
        self.assertEqual(set(result.keys()), {"a.py"})

    def test_returns_empty_dict_when_binary_missing(self):
        """No ruff on PATH → no fork, empty dict (matches run_linter)."""
        with patch("lint_check.shutil.which", return_value=None):
            result = lint_check.run_linter_batch(
                "ruff", ["a.py"], context="staging", cwd="/tmp"
            )
        self.assertEqual(result, {})

    def test_timeout_returns_empty_dict_not_per_path_clean(self):
        """A hung ruff must NOT silently report 'all paths clean' — that
        would let F401/F811 slip through the commit gate. Return {} on
        timeout (same shape as binary-missing) so callers can't confuse
        'we couldn't check' with 'we checked and found nothing'."""
        import subprocess as sp

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "lint_check.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="ruff", timeout=10),
            ),
        ):
            result = lint_check.run_linter_batch(
                "ruff",
                ["a.py", "b.py"],
                context="staging",
                cwd="/tmp",
            )
        self.assertEqual(result, {})

    def test_command_pins_concise_output_format(self):
        """ruff 0.15+ defaults to multi-line 'full' format which the per-line
        regex cannot parse — the batch must explicitly request 'concise' so
        F401/F811 codes actually surface. Pinned because a missing flag here
        silently empties the staging gate."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", ["a.py"], context="staging", cwd="/tmp")
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("--output-format=concise", cmd)


if __name__ == "__main__":
    unittest.main()
