#!/usr/bin/env python3
"""Tests for lint_check.py hook.

Split from the original test_post_tool.py.
"""

import os
import re
import shutil
import subprocess
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
import linters
import staged_lint
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


class TestRunRuffContext(_HookTestCase):
    """run_ruff is the single source of truth for EDIT-time ruff invocation.

    It drops F401/F811 (they false-positive mid-edit during multi-step
    replace_all migrations) and reports the rest as a concern.

    story-005 removed run_ruff's `context` parameter. Its "staging" branch
    preserved F401/F811 for a commit gate that no longer asks: the gate now
    classifies by exit code and blocks on ANY finding without reading a single
    code (a parser is per-language; the plugin ships to every language). Nothing
    called run_ruff at staging time once that landed, so the branch — and the
    two tests that pinned it — described a caller that does not exist.
    """

    def test_run_ruff_filters_F401(self):
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
            codes, _text = lint_check.run_ruff(Path("app.py"))
        self.assertNotIn("F401", codes)
        self.assertIn("E302", codes)

    def test_run_ruff_filters_F811(self):
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
            codes, _text = lint_check.run_ruff(Path("app.py"))
        self.assertEqual(codes, [])

    def test_run_ruff_filtered_text_excludes_filtered_lines(self):
        """Filtered output text should NOT mention F401."""
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
            _codes, text = lint_check.run_ruff(Path("app.py"))
        self.assertNotIn("F401", text)
        self.assertIn("E302", text)

    def test_run_ruff_returns_empty_when_ruff_clean(self):
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            codes, text = lint_check.run_ruff(Path("app.py"))
        self.assertEqual(codes, [])
        self.assertEqual(text, "")

    def test_run_ruff_returns_empty_when_binary_missing(self):
        with patch("lint_check.shutil.which", return_value=None):
            codes, text = lint_check.run_ruff(Path("app.py"))
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
            codes, _text = lint_check.run_ruff(Path("app.py"))
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
            codes, _text = lint_check.run_ruff(Path("app.py"))
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
    """run_linter_batch forks the linter ONCE over all paths and classifies the
    run by its EXIT CODE — it never parses what the linter said.

    story-005 rewrote the contract. It used to return ``{path: codes}`` scraped
    with a ruff-shaped regex (``path:line:col: F401``), pre-populating every
    path to ``[]`` *before* parsing. eslint/clippy/golangci-lint output matches
    none of that shape, so zero lines parsed, every path mapped to "clean", and
    a caller could not tell "we read it and it was clean" from "we could not
    read it at all" — a silently green commit gate in every language but Python.

    Knowing *that* a linter found something needs only its exit code; knowing
    *what* it found would need a per-language parser, which the project's
    cross-language guardrail forbids. So:

      * exit 0                    → CLEAN (nothing to parse is expected here —
                                    a clean ruff run prints "All checks passed!")
      * non-zero, with output     → FINDINGS, reported verbatim
      * non-zero, nothing to say  → UNVERIFIED (a bad read, not a pass)
      * binary missing / timeout  → UNVERIFIED — callers fail CLOSED
    """

    def test_one_fork_for_multiple_paths(self):
        """Single ruff invocation regardless of how many paths are passed."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", ["a.py", "b.py", "c.py"], cwd="/tmp")
        mock_run.assert_called_once()

    def test_exit_zero_is_clean_even_though_nothing_parses(self):
        """The other half of the false-clean fix, and the one that keeps every
        green commit green: a CLEAN ruff run prints 'All checks passed!', which
        matches no finding shape at all. If 'nothing parsed' meant 'unverified',
        this gate would fail closed on every clean commit in the repo."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(
                returncode=0, stdout="All checks passed!\n"
            )
            run = lint_check.run_linter_batch("ruff", ["a.py"], cwd="/tmp")
        self.assertEqual(run.status, "clean")

    def test_nonzero_exit_reports_output_verbatim(self):
        """Findings are handed back as the linter's own text, uninterpreted."""
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
            run = lint_check.run_linter_batch("ruff", ["a.py", "c.py"], cwd="/tmp")
        self.assertEqual(run.status, "findings")
        self.assertIn("F401", run.output)
        self.assertIn("E302", run.output)

    def test_findings_in_a_shape_no_python_parser_could_read(self):
        """THE cross-language pin. golangci-lint says nothing that looks like
        `path:line:col: CODE` — under the old regex contract this run parsed to
        zero findings and every path read back as clean. Exit code alone must
        carry it.

        The vehicle used to be clippy, and clippy was the wrong one to pin this
        with: it is DEGRADED, so `staged_lint` never hands it to this function at
        all, and the run being asserted here could not happen. golangci-lint is a
        row the gate really does BLOCK on, and its output is just as unreadable to
        a `path:line:col: CODE` regex — so the pin now guards a live path.
        """
        stderr = (
            "src/main.go:1:5: `io` imported and not used (typecheck)\n"
            "src/main.go:7:2: S1021: should merge variable declaration (gosimple)\n"
        )
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(returncode=1, stderr=stderr)
            run = lint_check.run_linter_batch(
                "golangci-lint", ["src/main.go"], cwd="/tmp"
            )
        self.assertEqual(run.status, "findings")
        self.assertIn("imported and not used", run.output)

    def test_a_linter_with_no_per_file_argv_is_unverified_never_clean(self):
        """clippy has no argv that asks about ONE file (it lints the crate), so
        `linter_argv` returns None. The batch must read that as a bad read, not as a
        pass — declining to look is not the same as having nothing to look at.

        Unreachable in production (the row degrades before the batch is called), and
        pinned anyway: it is the fail-closed floor under the degrade, and a future row
        that loses its degrade entry must not fall through to CLEAN.
        """
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/cargo"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            run = lint_check.run_linter_batch("clippy", ["src/main.rs"], cwd="/tmp")

        self.assertEqual(run.status, "unverified")
        mock_run.assert_not_called()

    def test_nonzero_exit_with_no_output_is_unverified(self):
        """The linter found something it could not tell us about. That is a bad
        read, not a pass — the caller must fail closed."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result(returncode=2)
            run = lint_check.run_linter_batch("ruff", ["a.py"], cwd="/tmp")
        self.assertEqual(run.status, "unverified")

    def test_paths_passed_to_subprocess(self):
        """All paths appear after `--` in the ruff command line."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", ["a.py", "b.py"], cwd="/tmp")
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("--", cmd)
        sep = cmd.index("--")
        self.assertEqual(cmd[sep + 1 :], ["a.py", "b.py"])

    def test_empty_paths_is_clean_no_fork(self):
        """No path this linter claims → nothing to verify, and nothing to
        block on. A missing linter is not a finding."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            run = lint_check.run_linter_batch("ruff", [], cwd="/tmp")
        mock_run.assert_not_called()
        self.assertEqual(run.status, "clean")

    def test_skips_files_with_wrong_extension(self):
        """ruff only knows .py/.pyi/.ipynb — non-Python paths skipped, not forked on."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", ["a.py", "b.json", "c.md"], cwd="/tmp")
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        sep = cmd.index("--")
        self.assertEqual(cmd[sep + 1 :], ["a.py"])

    def test_flag_shaped_path_is_unverified_not_clean(self):
        """A path the arg-injection guard REFUSES to pass is a file we declined
        to check — unverified, so the gate fails closed.

        The two reasons a path gets dropped are not the same reason. An
        extension the linter does not claim is 'nothing to look at' (clean). A
        `-foo.py` is 'we would not look at it' — and reporting that as clean is
        a fail-OPEN: an unlinted file ships. The old contract caught this via
        its missing-path check; exit-code classification has to say it out loud.
        """
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            run = lint_check.run_linter_batch("ruff", ["-foo.py"], cwd="/tmp")
        mock_run.assert_not_called()
        self.assertEqual(run.status, "unverified")
        self.assertIn("-foo.py", run.output)

    def test_flag_shaped_path_beside_a_normal_one_still_unverified(self):
        """The refused path must not be quietly dropped while its neighbours
        lint clean — that reports a green run over an incomplete set."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            run = lint_check.run_linter_batch("ruff", ["-foo.py", "b.py"], cwd="/tmp")
        mock_run.assert_not_called()
        self.assertEqual(run.status, "unverified")

    def test_binary_missing_is_unverified(self):
        """A configured linter whose binary is absent is a bad read — the gate
        fails CLOSED. (A missing *config* is what skips; that decision belongs
        to the caller's detection step, not here.)"""
        with patch("lint_check.shutil.which", return_value=None):
            run = lint_check.run_linter_batch("ruff", ["a.py"], cwd="/tmp")
        self.assertEqual(run.status, "unverified")
        self.assertIn("ruff", run.output)

    def test_timeout_is_unverified(self):
        """A hung linter must NOT read as 'all clean' — that would let real
        findings slip through the commit gate."""
        import subprocess as sp

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "lint_check.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="ruff", timeout=10),
            ),
        ):
            run = lint_check.run_linter_batch("ruff", ["a.py", "b.py"], cwd="/tmp")
        self.assertEqual(run.status, "unverified")

    def test_command_pins_concise_output_format(self):
        """ruff 0.15+ defaults to a multi-line 'full' format. The gate no longer
        parses, so this no longer changes what blocks — but it is what the human
        reads out of the block message, and multi-line full output buries the
        codes. Keep it concise."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run") as mock_run,
        ):
            mock_run.return_value = _mock_ruff_result()
            lint_check.run_linter_batch("ruff", ["a.py"], cwd="/tmp")
        args, _kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("--output-format=concise", cmd)


# ===========================================================================
# Story-006: the commit lint gate gates the bytes it COMMITS, not the bytes on
# disk — and it judges them at the file's REAL path.
#
# The placement has oscillated, and both previous answers were copies. A temp
# sibling (random basename) defeated filename-keyed rules. A temp subdir kept the
# basename but sat one level down, so `./util`, `../lib/x` and any path-keyed
# config rule resolved somewhere else — self-obscuring, since the tmp segment was
# stripped from the output and the dir deleted before the agent read it.
#
# Both properties are only satisfiable at the real path, so nothing is copied:
# lint in place where git says the index and the tree agree, pipe the staged
# bytes with --stdin-filename where they diverge, degrade where a linter reads
# no stdin.
# ===========================================================================


class TestLinterStdinShapes(unittest.TestCase):
    """The stdin column: HOW (and whether) a linter accepts source on stdin.

    A shape, not a bool — the three forms genuinely differ in argv, so a bool
    could not tell the caller what to build. Absent rows answer NO_STDIN, so a
    linter nobody filled in degrades (advisory) rather than being mis-invoked.
    """

    def test_ruff_takes_a_trailing_dash(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("ruff"),
            linters.STDIN_FILENAME_TRAILING_DASH,
        )

    def test_eslint_takes_a_stdin_flag_and_no_positional(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("eslint"),
            linters.STDIN_FLAG_AND_FILENAME,
        )

    def test_prettier_names_the_path_with_its_own_flag(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("prettier"),
            linters.STDIN_FILEPATH,
        )

    def test_absent_row_defaults_to_no_stdin(self):
        """The default is the SAFE direction: a linter with no row cannot be
        fed stdin, so the caller degrades to an advisory instead of inventing
        an argv the tool would reject. A forgotten column must not
        mis-invoke."""
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("clang-tidy", linters.NO_STDIN),
            linters.NO_STDIN,
        )
        self.assertNotIn("clang-tidy", linters.LINTER_STDIN_SHAPES)

    def test_flake8_takes_a_display_name_and_a_trailing_dash(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("flake8"),
            linters.STDIN_DISPLAY_NAME_TRAILING_DASH,
        )

    def test_rubocop_names_the_path_as_the_stdin_flags_value(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("rubocop"),
            linters.STDIN_FLAG_WITH_FILENAME,
        )

    def test_clang_format_assumes_the_filename(self):
        self.assertEqual(
            linters.LINTER_STDIN_SHAPES.get("clang-format"),
            linters.STDIN_ASSUME_FILENAME,
        )

    def test_every_row_names_a_linter_that_exists(self):
        """A row for a linter the registry cannot invoke is dead data — it
        would never be reached, and reads as coverage that is not there."""
        for name in linters.LINTER_STDIN_SHAPES:
            self.assertIn(name, linters.LINTER_COMMANDS, f"{name} has no command")

    def test_every_shape_the_table_carries_builds_an_argv_naming_the_path(self):
        """The keys are pinned above; the VALUES are what the caller dispatches
        on, and they are pinned nowhere else except one test per linter.

        A row naming a shape `linter_stdin_argv` has no `case` for clears the
        gate's NO_STDIN check (it is not NO_STDIN, so nothing degrades), then
        falls off the match to None — which `run_linter_stdin` reports as
        `unverified`, a BLOCK nobody can fix, on every divergent file for that
        linter. The absent-row default fails safe; a WRONG row does not, and
        that is the gap between them.

        The path assertion is the story's whole thesis: the bytes go down stdin
        precisely so the linter can still be TOLD the real path they belong to.
        A shape that pipes without naming the path silently reintroduces the
        unlocatable finding the temp copies produced.
        """
        for name, shape in linters.LINTER_STDIN_SHAPES.items():
            with self.subTest(linter=name, shape=shape):
                self.assertNotEqual(
                    shape, linters.NO_STDIN, "a row saying NO_STDIN is a row to delete"
                )
                argv = linters.linter_stdin_argv(name, "pkg/app.src", root="/repo")
                self.assertIsNotNone(argv, f"{shape} builds no argv — unfixable block")
                self.assertIn(
                    "pkg/app.src",
                    argv or [],
                    f"{shape} pipes the bytes without naming the path",
                )


class TestNoActiveLinterSilentlyLosesTheIndex(unittest.TestCase):
    """The set of linters that cannot judge divergent staged bytes, pinned.

    A linter that is neither degraded nor stdin-capable has no way to read what
    the commit carries once the index and the tree diverge, so its whole language
    loses the gate's headline guarantee for those files. That is a real cost, and
    this test is what stops the set growing by ACCIDENT: it grew silently once
    already, when materialization was removed and every non-stdin linter quietly
    became advisory. Adding a name here must be a deliberate act with a reason
    written next to it in LINTER_STDIN_SHAPES, never a row somebody forgot.
    """

    # Each verified against the tool itself, not a doc page — see the reasoning
    # block above LINTER_STDIN_SHAPES for why each one is a NO_STDIN we CHOSE.
    _EXPECTED_UNCOVERED: frozenset[str] = frozenset(
        {
            "golangci-lint",
            "clang-tidy",
            "dart-analyze",
            "swiftlint",
            "phpcs",
            "php-cs-fixer",
        }
    )

    def test_the_uncovered_set_is_exactly_what_we_have_signed_off(self):
        uncovered = {
            name
            for name in linters.LINTER_COMMANDS
            if name not in linters.DEGRADED_LINTERS
            and linters.LINTER_STDIN_SHAPES.get(name, linters.NO_STDIN)
            == linters.NO_STDIN
        }
        self.assertEqual(
            uncovered,
            self._EXPECTED_UNCOVERED,
            "the set of linters that cannot judge a divergent staged file "
            "changed. Growing it drops commit-time index coverage for a whole "
            "language — fill in the stdin row, or record why it genuinely has "
            "none. Shrinking it is good news: update this expectation.",
        )


class TestTheColumnsAgreeOnWhoTheLintersAre(unittest.TestCase):
    """Every linter-keyed column keys the SAME linters — no orphan rows.

    The registry is a sparse matrix: one dict per COLUMN, ~18 linters, most cells
    empty. That shape is deliberate (a record per linter would force every row to
    answer every column, and the columns' rationale — why each is structural and
    not a rule-code map — is what keeps the cross-language guardrail honest). The
    cost it carries is DESYNC: a typo'd or renamed key is a row that silently
    never fires, and the gate then reports coverage it does not have.

    So the count of columns is not the risk; an unguarded column is. This pins
    every one of them at once, and a new column joins by being added to the list.
    """

    def _columns(self) -> dict[str, dict]:
        return {
            name: getattr(linters, name)
            for name in (
                "LINTER_STRICT_FLAGS",
                "LINTER_ARGV_SHAPES",
                "LINTER_STDIN_SHAPES",
                "LINTER_CONFIG_FLAGS",
                "LINTER_PRECONDITIONS",
                "DEGRADED_LINTERS",
                "LINTER_EXTENSIONS",
                "LINTER_BINARIES",
            )
        }

    def test_no_column_carries_a_row_for_an_uninvokable_linter(self):
        for column, table in self._columns().items():
            with self.subTest(column=column):
                orphans = set(table) - set(linters.LINTER_COMMANDS)
                self.assertEqual(
                    orphans, set(), f"{column} keys linters with no command: {orphans}"
                )

    def test_every_linter_a_config_can_select_can_be_invoked(self):
        """detect_linter_config answers off LINTER_CONFIGS; a name it can return
        that LINTER_COMMANDS does not carry is a KeyError at commit time — in a
        PreToolUse hook that is exit 1, which the harness reads as NON-blocking:
        the gate fails OPEN."""
        selectable = {linter for _, linter, _ in linters.LINTER_CONFIGS}
        self.assertEqual(selectable - set(linters.LINTER_COMMANDS), set())

    def test_every_invokable_linter_can_be_found_on_path(self):
        """`LINTER_BINARIES` is what every runner probes with `shutil.which`
        before running. A command with no binary row probes None and reports
        `unverified` — a block nobody can fix — for that whole ecosystem."""
        self.assertEqual(
            set(linters.LINTER_COMMANDS) - set(linters.LINTER_BINARIES), set()
        )


class _StagedGitRepo(unittest.TestCase):
    """A real git repo the staged-lint gate can resolve a root + index from."""

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(self.repo), check=True, capture_output=True
        )

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")
        (self.repo / "ruff.toml").touch()


class _LinterCallRecorder(_StagedGitRepo):
    """Intercept the LINTER while letting the gate's git reads run for real.

    `patch("lint_check.subprocess.run")` binds `run` on the shared subprocess
    module, so it also intercepts staged_lint's index reads — delegate anything
    git-shaped to the real runner and record only the linter invocations.
    """

    def _run_gate(self, paths: list[str], *, exit_code: int = 0, output: str = ""):
        real_run = subprocess.run
        calls: list[dict] = []

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            calls.append({"cmd": list(cmd), "kwargs": kwargs})
            return _mock_ruff_result(returncode=exit_code, stdout=output)

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            advisories = staged_lint.staged_lint_gate(paths, str(self.repo))
        return advisories, calls


class TestBranchBFeedsStagedBytesOnStdin(_LinterCallRecorder):
    """Where the index and the tree DIVERGE, the bytes to judge are not on disk.

    They are piped to the linter, which is told the path they belong to — so the
    file is judged at its REAL location without a copy existing anywhere. This is
    the case materialization was invented for, and it is why the hybrid beats a
    fast-path-only design: it fixes that case rather than conceding it.

    Per-file rather than batched, which is the honest cost: stdin carries one
    file. Divergence is rare (a partial add, an edit-after-add), so the cost is
    bounded by how rare it is, and the ~99% case stays batched.
    """

    def _stage_then_dirty(self) -> None:
        target = self.repo / "app.py"
        target.write_text("STAGED_CONTENT = 1\n")
        self._git("add", "app.py")
        target.write_text("WORKING_TREE_CONTENT = 2\n")

    def test_the_staged_bytes_are_piped_not_the_working_tree(self) -> None:
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["kwargs"].get("input"),
            b"STAGED_CONTENT = 1\n",
            "the linter must be fed the bytes the COMMIT carries",
        )

    def test_the_linter_is_told_the_real_path_those_bytes_belong_to(self) -> None:
        """The whole point: no temp file, and the path the linter resolves
        `./util` and filename-keyed rules against is the real one."""
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        cmd = calls[0]["cmd"]
        self.assertIn("--stdin-filename", cmd)
        self.assertEqual(cmd[cmd.index("--stdin-filename") + 1], "app.py")
        for arg in cmd:
            self.assertNotIn("tmp", arg, f"a temp path leaked into the argv: {arg}")

    def test_the_bytes_are_piped_as_bytes(self) -> None:
        """A staged blob may not be UTF-8, so `staged_blob_bytes` hands back raw
        bytes — which cannot be `input=` to a text-mode process. This branch runs
        binary and decodes the OUTPUT itself; a text-mode run would raise
        TypeError on the first non-UTF-8 blob and block a commit unfixably."""
        self._stage_then_dirty()

        _advisories, calls = self._run_gate(["app.py"])

        self.assertIsInstance(calls[0]["kwargs"].get("input"), bytes)
        self.assertNotEqual(calls[0]["kwargs"].get("text"), True)

    def test_a_non_utf8_staged_blob_does_not_crash_the_gate(self) -> None:
        target = self.repo / "app.py"
        target.write_bytes(b"# \xff\xfe not utf-8\nx = 1\n")
        self._git("add", "app.py")
        target.write_bytes(b"y = 2\n")

        _advisories, calls = self._run_gate(["app.py"])

        self.assertEqual(
            calls[0]["kwargs"].get("input"), b"# \xff\xfe not utf-8\nx = 1\n"
        )

    def _run_gate_with_bytes(self, paths: list[str], *, stdout: bytes, code: int):
        """Branch B runs the linter in BINARY mode, so its stdout is bytes —
        `_mock_ruff_result` is typed for the text-mode callers."""
        real_run = subprocess.run

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return type(
                "R", (), {"returncode": code, "stdout": stdout, "stderr": b""}
            )()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            return staged_lint.staged_lint_gate(paths, str(self.repo))

    def test_findings_name_the_file_even_when_the_linter_will_not(self) -> None:
        """A linter fed stdin may name its input `(stdin)` instead of the path it
        was told — MEASURED: prettier 3 `--check --stdin-filepath x.js` prints
        exactly `(stdin)` and exits 1. Branch B is per-file, so the gate KNOWS
        which file the run was for, and must say so: a finding the agent cannot
        locate is this story's own scar (a report against a path that is not the
        file). The gate never reads the linter's words — it only labels them."""
        self._stage_then_dirty()

        with self.assertRaises(_common.BlockedError) as ctx:
            self._run_gate_with_bytes(["app.py"], stdout=b"(stdin)\n", code=1)

        self.assertIn("app.py", ctx.exception.args[0])
        self.assertIn("(stdin)", ctx.exception.args[0], "the linter's own words")

    def test_linter_output_is_decoded_leniently(self) -> None:
        """The linter's own bytes are not guaranteed UTF-8 either (it echoes the
        source line it flagged). Findings must survive a bad byte, not raise."""
        target = self.repo / "app.py"
        target.write_text("import os\n")
        self._git("add", "app.py")
        target.write_text("x = 1\n")

        real_run = subprocess.run

        # Not _mock_ruff_result: this branch runs the linter in BINARY mode, so
        # its stdout is bytes, and that fixture is typed for the text-mode
        # callers. Faking bytes here is the point of the test.
        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return type(
                "R",
                (),
                {"returncode": 1, "stdout": b"app.py:1:1: F401 \xff\n", "stderr": b""},
            )()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", ctx.exception.args[0])

    def test_a_spent_budget_says_what_to_do_about_it(self) -> None:
        """This branch costs a process per file, so a commit with many divergent
        files can spend the shared budget — and a spent budget BLOCKS.

        Normally that is the one `unverified` cause nobody can act on: you cannot
        make a linter faster. Here they can, and the message has to say so. The
        file is only on this expensive path because its staged bytes differ from
        the file on disk; re-staging it stops the divergence and routes it back
        through the shared batch. An unfixable gate gets switched off — which is
        the one outcome worse than a quiet one.
        """
        run = lint_check.run_linter_stdin(
            "ruff",
            "app.py",
            b"x = 1\n",
            cwd=str(self.repo),
            budget_s=0,
            root=str(self.repo),
        )

        self.assertEqual(run.status, "unverified", "a spent budget is not a pass")
        self.assertIn(
            "git add app.py", run.output, "name the remedy, not just the cause"
        )


class TestBranchCBlocksWhenStdinIsNotAnOption(_StagedGitRepo):
    """Divergent bytes + a linter that reads no stdin = FAIL CLOSED, and say how.

    This branch used to advise and wave the commit through, which reopened the
    exact edit-after-add fail-open the gate exists to close — for every language
    whose linter takes no stdin (Go, C/C++, Dart, Swift, PHP). The reasoning that
    licensed it was that blocking is "a gate nobody can satisfy". That is false,
    and the falseness is the whole point: `git add <path>` satisfies it in one
    command, and for the headline case (staged, then edited on disk) re-staging
    is what the committer MEANT to do anyway. An unreadable file is not a clean
    one — the gate's own doctrine everywhere else.

    Narrow by construction: only a divergent file, only for a stdin-less linter.
    Identical files still lint in place on branch A — ~99% of commits.
    """

    def _stage_then_dirty_a_go_file(self) -> None:
        (self.repo / ".golangci.yml").touch()
        target = self.repo / "main.go"
        target.write_text("package main\nfunc main() { var x int }\n")  # violation
        self._git("add", "main.go")
        target.write_text("package main\nfunc main() {}\n")  # fixed, NOT re-staged

    def test_divergent_file_for_a_stdin_less_linter_blocks(self) -> None:
        """The regression this class is named for: on a Go project, the
        violating STAGED bytes must not reach the commit just because the
        working tree was cleaned up afterwards."""
        self._stage_then_dirty_a_go_file()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            self.assertRaises(_common.BlockedError) as caught,
        ):
            staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        message = str(caught.exception)
        self.assertIn("main.go", message, "the block must name the file")
        self.assertIn("golangci-lint", message, "and the linter that cannot read it")

    def test_the_block_tells_the_committer_how_to_satisfy_it(self) -> None:
        """A gate that blocks without naming its remedy is the unsatisfiable
        gate the old advisory was (wrongly) afraid of."""
        self._stage_then_dirty_a_go_file()

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            self.assertRaises(_common.BlockedError) as caught,
        ):
            staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        self.assertIn("git add", str(caught.exception))

    def test_an_IDENTICAL_go_file_still_lints_in_place_and_passes(self) -> None:
        """The loss stays narrow: divergence is the trigger, not the language."""
        (self.repo / ".golangci.yml").touch()
        (self.repo / "main.go").write_text("package main\nfunc main() {}\n")
        self._git("add", "main.go")  # index == working tree

        real_run = subprocess.run

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return _mock_ruff_result(returncode=0, stdout="")

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/golangci-lint"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            advisories = staged_lint.staged_lint_gate(["main.go"], str(self.repo))

        self.assertEqual(advisories, [])

    def test_a_project_scoped_linter_still_DEGRADES_rather_than_blocking(self) -> None:
        """The distinction this change must not flatten: clippy exits non-zero
        over whole-crate state the staged diff neither caused nor can fix, so
        blocking on it is genuinely unsatisfiable. `degrade_reason` runs first
        and still wins — divergence never reaches it."""
        (self.repo / "Cargo.toml").touch()
        target = self.repo / "main.rs"
        target.write_text("fn main() { let x = 1; }\n")
        self._git("add", "main.rs")
        target.write_text("fn main() {}\n")  # divergent

        with patch("lint_check.shutil.which", return_value="/usr/bin/cargo"):
            advisories = staged_lint.staged_lint_gate(["main.rs"], str(self.repo))

        self.assertEqual(len(advisories), 1, f"expected one advisory: {advisories}")
        self.assertIn("clippy", advisories[0])


class TestBranchALintsTheRealPath(_LinterCallRecorder):
    """When the index and the working tree AGREE, the file on disk IS the staged
    blob — so lint it where it lives. No copy, at any depth.

    Every copy breaks something. A temp sibling (random basename) defeats
    filename-keyed rules; a temp subdir keeps the basename but shifts the file
    one level down, so `./util` and `../lib/x` resolve to paths that do not
    exist — and the gate then reports an unresolved import against a real path
    that is provably clean. Both properties hold only at the real path.

    This cannot reintroduce the partial-add fail-open: that hole requires the
    index and the tree to DIVERGE, and this branch only fires when they are
    byte-identical by git's own account.
    """

    def _stage_two_identical_files(self) -> None:
        (self.repo / "app.py").write_text("x = 1\n")
        (self.repo / "util.py").write_text("y = 2\n")
        self._git("add", "app.py", "util.py")

    def test_the_real_paths_are_linted_not_a_copy(self) -> None:
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        self.assertEqual(len(calls), 1, "one batched invocation")
        cmd = calls[0]["cmd"]
        self.assertIn("app.py", cmd)
        self.assertIn("util.py", cmd)

    def test_no_temp_directory_is_created_anywhere(self) -> None:
        """The whole story: no copy, so no shifted depth. Assert on the argv,
        which is what the linter actually resolves paths from."""
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        for arg in calls[0]["cmd"]:
            self.assertNotIn("tmp", arg, f"a temp segment leaked into the argv: {arg}")
        strays = [p.name for p in self.repo.iterdir() if p.name.startswith("tmp")]
        self.assertEqual(strays, [], f"temp dirs created in the repo: {strays}")

    def test_still_one_subprocess_for_many_paths(self) -> None:
        """Batching is load-bearing, not incidental. A per-file invocation costs
        one process per staged file — 50 spawns on a 50-file commit, inside a
        hook the harness will kill. If it is killed there is no exit 2, so the
        commit lands UNLINTED: the fail-open this gate exists to close."""
        for i in range(12):
            (self.repo / f"mod{i}.py").write_text(f"v{i} = {i}\n")
        self._git("add", ".")

        _advisories, calls = self._run_gate([f"mod{i}.py" for i in range(12)])

        self.assertEqual(len(calls), 1, "12 staged files must cost ONE subprocess")

    def test_no_stdin_is_fed_when_the_index_matches(self) -> None:
        """The file on disk already holds the staged bytes — piping them would
        be a per-file invocation bought for nothing."""
        self._stage_two_identical_files()

        _advisories, calls = self._run_gate(["app.py", "util.py"])

        self.assertIsNone(calls[0]["kwargs"].get("input"))

    def test_the_same_branch_carries_any_language(self) -> None:
        """Language-blindness, re-expressed after materialization died: routing
        is the linter TABLE, not a per-language branch, so a .go file takes the
        identical path. Its linter is unconfigured here, so the observable fact
        is that it is skipped rather than mishandled — no branch inspects the
        extension."""
        (self.repo / "main.go").write_bytes(b"package main\n")
        self._git("add", "main.go")

        advisories, calls = self._run_gate(["main.go"])

        self.assertEqual(advisories, [])
        self.assertEqual(calls, [], "no linter claims .go here — a skip, not a crash")


class TestIgnoredFileDoesNotBlock(unittest.TestCase):
    """A staged file the project's own config says to SKIP must not block it.

    This is a regression the real-path branches CREATE, and it is handled here
    rather than after the fact. Today the gate lints a temp copy, whose path an
    exact-path ignore pattern does not match — so an ignored file is linted
    anyway (a latent bug: the gate lints files the project says to skip). Put
    the file back at its real path and the ignore finally matches, at which
    point eslint reports `File ignored because of a matching ignore pattern`
    as a WARNING — and `--max-warnings=0`, which the strictness column ships to
    make warn-level rules block, turns that into exit 1. The gate would refuse a
    file the config says to skip, with nothing the committer could fix.

    MEASURED against eslint v10, both branches: an ignored file passed by path
    exits 1, and the same file passed via `--stdin-filename` exits 1 too.
    `--no-warn-ignored` returns both to exit 0.

    The flag is keyed on the CONFIG FILE, not on eslint, and that is
    load-bearing: it is accepted only in flat-config mode (added 8.51). Under
    `.eslintrc` — any version — it is an unrecognized option, which exits 2 with
    nothing linted. The gate reads non-zero-with-output as FINDINGS, so shipping
    it unconditionally would block EVERY commit in every eslintrc project: far
    worse than the narrow bug it fixes.
    """

    def _argv(self, config_name: str) -> list[str]:
        return (
            linters.linter_argv(
                "eslint",
                ["app.js"],
                root="/repo",
                config_path=f"/repo/{config_name}",
            )
            or []
        )

    def test_flat_config_suppresses_the_ignored_file_warning(self):
        self.assertIn("--no-warn-ignored", self._argv("eslint.config.js"))

    def test_flat_config_variants_all_carry_it(self):
        for name in ("eslint.config.js", "eslint.config.mjs", "eslint.config.ts"):
            with self.subTest(config=name):
                self.assertIn("--no-warn-ignored", self._argv(name))

    def test_eslintrc_does_not_get_a_flag_it_would_reject(self):
        """Unrecognized option → exit 2, nothing linted, every commit blocked."""
        for name in (".eslintrc", ".eslintrc.json", ".eslintrc.js"):
            with self.subTest(config=name):
                self.assertNotIn("--no-warn-ignored", self._argv(name))

    def test_the_suppression_rides_with_the_strictness_that_needs_it(self):
        """`--max-warnings=0` is what turns the warning into a block, so the two
        must be composed by the SAME builder. Split them and a caller can pin
        strictness without the suppression and reintroduce the block."""
        argv = self._argv("eslint.config.js")
        self.assertIn("--max-warnings=0", argv)
        self.assertIn("--no-warn-ignored", argv)

    def test_no_config_path_stays_conservative(self):
        """Mode unknown → do not guess. A flag the tool might reject is worse
        than a warning it might emit."""
        argv = linters.linter_argv("eslint", ["app.js"], root="/repo") or []
        self.assertNotIn("--no-warn-ignored", argv)

    def test_a_linter_with_no_config_style_row_is_untouched(self):
        argv = linters.linter_argv("ruff", ["app.py"], root="/repo") or []
        self.assertNotIn("--no-warn-ignored", argv)

    def test_the_stdin_branch_carries_it_too(self):
        """AC4 holds on BOTH branches or it does not hold. The docstring says
        MEASURED on both, and an ignored file exits 1 via `--stdin-filename`
        exactly as it does by path — so a divergent ignored file would block
        unfixably if only the in-place branch were fixed. `_argv_prefix` is
        shared to make that impossible; this is the test that says so."""
        argv = (
            linters.linter_stdin_argv(
                "eslint",
                "app.js",
                root="/repo",
                config_path="/repo/eslint.config.js",
            )
            or []
        )
        self.assertIn("--no-warn-ignored", argv)
        self.assertIn("--max-warnings=0", argv)

    def test_the_stdin_branch_withholds_it_from_eslintrc_too(self):
        argv = (
            linters.linter_stdin_argv(
                "eslint", "app.js", root="/repo", config_path="/repo/.eslintrc.json"
            )
            or []
        )
        self.assertNotIn("--no-warn-ignored", argv)


# TestMaterializeIsLanguageBlind and TestMaterializeCreatesMissingParentDir stood
# here. Both tested `_materialize_staged` directly, which no longer exists — the
# gate lints the real path, so there is no copy to key on a basename and no
# gone-parent-dir to recreate. Their INTENT survives: language-blindness is pinned
# by TestBranchALintsTheRealPath.test_the_same_branch_carries_any_language, and the
# staged-new file whose parent dir is gone is pinned end-to-end by
# TestGateHandlesMissingParentDir — which needs no dir on disk at all now, because
# the bytes arrive on stdin.


class TestGateFailsClosedOnAnUnreadableStagedBlob(_StagedGitRepo):
    """An in-index file whose staged blob cannot be read is a bad read →
    unverified → BLOCK. Never a silent skip.

    `staged_blob_bytes` survives the death of materialization: it is now the
    source of the bytes branch B pipes to the linter, so this is still the read
    that can fail, and it must still fail closed.
    """

    def test_unreadable_staged_blob_blocks(self) -> None:
        target = self.repo / "app.py"
        target.write_text("import os\n")
        self._git("add", "app.py")

        with (
            patch("staged_lint.staged_blob_bytes", return_value=None),
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            self.assertRaises(_common.BlockedError),
        ):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))


class TestStagedDeletionSkipsOnIndexMembership(_StagedGitRepo):
    """AC3: a staged deletion is skipped via INDEX membership, not `.exists()`.

    The working-tree copy is left present AND dirty, so an `.exists()`-based
    predicate would lint the dirty working tree and block; only the index check
    (the blob is gone from `:app.py`) correctly skips it.
    """

    def test_staged_deletion_with_dirty_worktree_is_skipped(self) -> None:
        target = self.repo / "app.py"
        target.write_text("x = 1\n")
        self._git("add", "app.py")
        self._git("commit", "-q", "-m", "add app")
        self._git("rm", "--cached", "app.py")  # stage the deletion, keep the file
        target.write_text("import os\n")  # dirty, F401-violating working-tree copy

        advisories = staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertEqual(
            advisories, [], "a staged deletion must be skipped, not linted or blocked"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateSeesPastTheIndexsDoNotLookBits(_StagedGitRepo):
    """`git diff` is stat-first, and two index bits switch the stat off.

    `assume-unchanged` and `skip-worktree` both tell git to stop comparing a
    file against the working tree -- so `git diff --name-only` does not NAME a
    file whose index and disk contents genuinely differ, and the gate routes it
    to the in-place branch and lints the wrong bytes. Delegating the question to
    git is right (only git applies the project's own clean/smudge and eol
    filters, which raw bytes would read as spurious divergence); trusting a
    stat-first answer for files git has been told not to stat is not.

    `git ls-files -v` reports those bits directly, for the whole staged set in
    one process, so the cheap batched design is kept and the hole is closed.
    """

    def _stage_violation_then_clean_disk_with(self, bit: str) -> None:
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401, the bytes the commit carries
        self._git("add", "app.py")
        self._git("update-index", bit, "app.py")
        target.write_text("x = 1\n")  # disk is clean; git has been told not to look

    def test_assume_unchanged_still_lints_the_staged_bytes(self) -> None:
        self._stage_violation_then_clean_disk_with("--assume-unchanged")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", str(ctx.exception))

    def test_skip_worktree_still_lints_the_staged_bytes(self) -> None:
        self._stage_violation_then_clean_disk_with("--skip-worktree")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertIn("F401", str(ctx.exception))

    def test_an_ordinary_clean_file_is_unaffected(self) -> None:
        """The guard must not sweep every file onto the slow path."""
        (self.repo / "app.py").write_text("x = 1\n")
        self._git("add", "app.py")

        self.assertEqual(staged_lint.staged_lint_gate(["app.py"], str(self.repo)), [])


class TestGateBlocksOnRealStagedBytes(_StagedGitRepo):
    """End-to-end against the REAL ruff, the whole point of the story."""

    def test_ac1_ac5_staged_violation_fixed_on_disk_still_blocks(self) -> None:
        """Stage a violation, clean the working tree — the gate blocks on the
        bytes the commit CARRIES (the partial-add fail-open)."""
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401
        self._git("add", "app.py")
        target.write_text("x = 1\n")  # working tree is clean now

        with self.assertRaises(_common.BlockedError):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

    def test_block_message_names_the_real_file_not_the_temp(self) -> None:
        """The finding must name `app.py` and no path but `app.py` — the agent is
        told to fix it, so the path it reads must be one that exists.

        The copy this once guarded against is gone, and the guard stays: it pins
        the PROPERTY (a block names a real path), not the mechanism. Both prior
        designs satisfied their own mechanism and broke this."""
        target = self.repo / "app.py"
        target.write_text("import os\n")  # F401
        self._git("add", "app.py")

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        message = ctx.exception.args[0]
        self.assertIn("app.py:", message, "must name the real staged file")
        # No mkstemp temp sibling (app.<random>.py) leaked into the message.
        self.assertIsNone(re.search(r"app\.[A-Za-z0-9_]+\.py", message))

    def test_ac2_staged_clean_working_tree_dirty_proceeds(self) -> None:
        """Stage clean bytes, dirty the working tree — no block: the gate does
        not judge bytes the commit is not carrying."""
        target = self.repo / "app.py"
        target.write_text("x = 1\n")  # clean
        self._git("add", "app.py")
        target.write_text("import os\n")  # working-tree violation, NOT staged

        advisories = staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertEqual(
            advisories, [], "must not block on unstaged working-tree bytes"
        )

    def test_no_temp_files_left_behind(self) -> None:
        """The gate must leave the working tree exactly as it found it.

        There is no copy to clean up any more, so this no longer guards a
        cleanup path — it guards the INVARIANT that replaced it: a gate that
        writes nothing cannot strand anything. It fails the moment someone
        reaches for a temp copy again, which is the third time this would be."""
        target = self.repo / "app.py"
        target.write_text("x = 1\n")
        self._git("add", "app.py")

        staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        strays = [
            p.name
            for p in self.repo.iterdir()
            if p.name.startswith("app.") and p.name != "app.py"
        ]
        self.assertEqual(strays, [], f"temp siblings stranded in the repo: {strays}")


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGatePreservesFilenameKeyedRules(_StagedGitRepo):
    """A linter rule keyed on the EXACT basename (ruff `per-file-ignores`,
    eslint filename globs, `__init__.py`/`conftest.py` special-cases) must match
    the file the gate lints. A random temp NAME defeats those rules and turns a
    legitimate commit into a FALSE-POSITIVE block — the inverse of the documented
    fail-open, and the reason the temp SIBLING design was abandoned.

    The basename is now exact because the path is the real one, on every branch:
    linted in place, or piped and named with `--stdin-filename`.
    """

    def test_per_file_ignore_by_exact_basename_still_applies(self) -> None:
        (self.repo / "ruff.toml").write_text(
            '[lint.per-file-ignores]\n"__init__.py" = ["F401"]\n'
        )
        pkg = self.repo / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("import os\n")  # F401, ignored for __init__.py
        self._git("add", "pkg/__init__.py")

        # A random temp name (pkg/__init__.RANDOM.py) escapes the __init__.py
        # per-file-ignore, ruff flags F401, and the gate blocks a legitimate
        # commit. Preserving the exact basename keeps the ignore matching.
        advisories = staged_lint.staged_lint_gate(["pkg/__init__.py"], str(self.repo))
        self.assertEqual(
            advisories, [], "filename-keyed per-file-ignore must still apply"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateJudgesTheFileAtItsRealDepth(_StagedGitRepo):
    """AC1/AC5 end-to-end, through a real linter subprocess: a staged file is
    judged at the path it really occupies — right basename AND right depth.

    Depth is what the previous fix traded away. Materializing to `pkg/tmpXXXX/
    app.py` keeps the basename but moves the file one level DOWN, so every
    path-relative resolution the file does (`./util`, `../lib/x`) and every
    config rule keyed on a PATH resolves somewhere else. Self-obscuring, too:
    the tmp segment was stripped from the output and the directory deleted, so
    the agent saw a finding against a real path that was provably clean.

    A literal `./util` import is NOT the probe here, and that is deliberate:
    ruff does not resolve imports, so a relative-import test exits 0 whether the
    file sits at its real depth or one level below it. It would pass against the
    OLD code too — an inert test, which is this milestone's exact scar. The
    falsifiable probe is a config rule keyed on the file's PATH, which fails
    over depth for the same reason and MEASURABLY reddens: at `pkg/app.py` real
    ruff exits 0; at `pkg/tmpXXXX/app.py` it exits 1 with F401.
    """

    def setUp(self) -> None:
        super().setUp()
        # Keyed on the PATH, not just the basename: it only matches at the real
        # depth. A per-file-ignore is ordinary config, in every language's linter.
        (self.repo / "ruff.toml").write_text(
            '[lint.per-file-ignores]\n"pkg/app.py" = ["F401"]\n'
        )
        self.pkg = self.repo / "pkg"
        self.pkg.mkdir()
        (self.pkg / "util.py").write_text("X = 1\n")

    def test_ac1_a_relative_importing_pair_does_not_block(self) -> None:
        """Both files staged and identical to the tree — branch A, real paths."""
        (self.pkg / "app.py").write_text("from .util import X\n")
        self._git("add", "pkg/app.py", "pkg/util.py")

        advisories = staged_lint.staged_lint_gate(
            ["pkg/app.py", "pkg/util.py"], str(self.repo)
        )

        self.assertEqual(advisories, [], "a file at its real path must not block")

    def test_ac3_the_same_holds_when_the_staged_bytes_diverge(self) -> None:
        """Branch B: the bytes go down stdin, but the PATH they are labelled
        with is still the real one, so the path-keyed rule still matches."""
        app = self.pkg / "app.py"
        app.write_text("from .util import X\n")
        self._git("add", "pkg/app.py", "pkg/util.py")
        app.write_text("from .util import X\nY = 2\n")  # divergent

        advisories = staged_lint.staged_lint_gate(
            ["pkg/app.py", "pkg/util.py"], str(self.repo)
        )

        self.assertEqual(advisories, [])

    def test_ac5_mangling_the_staged_bytes_DOES_block(self) -> None:
        """The other half of the proof: the gate is reading these bytes, not
        waved through. Same file, same real path, a violation the path-keyed
        ignore does not cover — and the working tree left clean, so only the
        STAGED bytes can be what blocks it."""
        app = self.pkg / "app.py"
        app.write_text("from .util import X\nprint(NO_SUCH_NAME)\n")  # F821
        self._git("add", "pkg/app.py", "pkg/util.py")
        app.write_text("from .util import X\n")  # working tree is clean

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["pkg/app.py", "pkg/util.py"], str(self.repo))

        message = ctx.exception.args[0]
        self.assertIn("F821", message, "the STAGED bytes are what is judged")
        self.assertIn("pkg/app.py", message, "and it names the real file")
        self.assertNotIn("tmp", message, "no temp path may reach the agent")


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateHandlesMissingParentDir(_StagedGitRepo):
    """A staged-new file whose parent dir is gone in the working tree (index
    still carries it) must not fail the gate closed.

    Kept, and it gets easier rather than harder: git calls the file divergent, so
    its bytes arrive on stdin and nothing needs to exist on disk at all. The old
    materialize had to RECREATE the missing dir to write its copy into, then
    remove it again to leave the tree as it found it — a whole mechanism for a
    case that stops existing once nothing is written.
    """

    def test_staged_new_file_whose_parent_dir_is_gone_is_not_blocked(self) -> None:
        import shutil as sh

        newdir = self.repo / "newdir"
        newdir.mkdir()
        (newdir / "foo.py").write_text("x = 1\n")  # clean
        self._git("add", "newdir/foo.py")
        sh.rmtree(newdir)  # index keeps the blob; the working tree loses the dir
        self.assertFalse(newdir.exists())

        advisories = staged_lint.staged_lint_gate(["newdir/foo.py"], str(self.repo))
        self.assertEqual(advisories, [], "a gone parent dir must not block the commit")
        self.assertFalse(
            newdir.exists(), "the recreated parent dir must be cleaned up after"
        )


class TestStagedBlobReadIsUnambiguous(_StagedGitRepo):
    """A staged path that itself begins `N:` collides with git's `:<stage>:<path>`
    shorthand: `:0:x.py` parses as stage 0 of `x.py`, not the file literally named
    `0:x.py`. The index read must address the stage explicitly (`:0:0:x.py`) so a
    hostile path cannot resolve to a different file's blob.
    """

    def test_colon_bearing_path_reads_its_own_staged_blob_not_a_collision(
        self,
    ) -> None:
        (self.repo / "0:x.py").write_text("A")
        (self.repo / "x.py").write_text("B")
        self._git("add", "0:x.py", "x.py")

        self.assertEqual(staged_lint.staged_blob_bytes(str(self.repo), "0:x.py"), b"A")

    def test_unreadable_blob_still_returns_none(self) -> None:
        self.assertIsNone(staged_lint.staged_blob_bytes(str(self.repo), "missing.py"))

    def test_ordinary_path_still_reads_its_own_staged_bytes(self) -> None:
        (self.repo / "app.py").write_text("x = 1\n")
        self._git("add", "app.py")

        self.assertEqual(
            staged_lint.staged_blob_bytes(str(self.repo), "app.py"), b"x = 1\n"
        )


@unittest.skipUnless(shutil.which("ruff"), "ruff not installed")
class TestGateBlocksOnCollisionNamedStagedBlob(_StagedGitRepo):
    """E2E: a staged file whose name collides under `:<stage>:<path>` parsing,
    carrying a real lint finding, must BLOCK the commit gate rather than
    silently linting the decoy and reporting clean."""

    def test_collision_named_file_with_lint_finding_blocks(self) -> None:
        (self.repo / "0:x.py").write_text("import os\n")  # F401, the staged bytes
        (self.repo / "x.py").write_text("y = 1\n")  # clean decoy the ambiguous ref
        # resolves to under the bug
        self._git("add", "0:x.py", "x.py")
        # Diverge the worktree copy so the gate takes the stdin branch and must
        # read the STAGED blob via `staged_blob_bytes` — the path the bug hits.
        (self.repo / "0:x.py").write_text("y = 2\n")

        with self.assertRaises(_common.BlockedError):
            staged_lint.staged_lint_gate(["0:x.py", "x.py"], str(self.repo))


if __name__ == "__main__":
    unittest.main()
