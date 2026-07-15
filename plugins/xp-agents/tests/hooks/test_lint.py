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
# Story-006: the commit lint gate gates the bytes it COMMITS, not the bytes
# on disk. git names STAGED paths but the linter used to read the WORKING-TREE
# copy, so under partial-add / edit-after-add the gate failed OPEN. Fix:
# materialize each staged blob to an in-dir temp sibling and lint THAT.
# ===========================================================================


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


class TestGateMaterializesStagedBytes(_StagedGitRepo):
    """The linter must be handed the STAGED bytes, not the working-tree copy.

    Deterministic proof with the linter mocked: stage content X, overwrite the
    working tree with content Y, and assert the file the linter is pointed at
    holds X — and is a real, readable file it would PROCESS, so a future
    silent-skip (glob / force-exclude) regression trips here too.
    """

    def test_linter_reads_staged_bytes_not_working_tree(self) -> None:
        target = self.repo / "app.py"
        target.write_text("STAGED_CONTENT = 1\n")
        self._git("add", "app.py")
        target.write_text("WORKING_TREE_CONTENT = 2\n")

        seen: dict[str, str] = {}
        # patch("lint_check.subprocess.run") binds `run` on the shared subprocess
        # module, so it also intercepts staged_lint's git calls — delegate those
        # to the real runner and only mock the linter invocation.
        real_run = subprocess.run

        def _capture(cmd, **kwargs):
            if cmd and cmd[0] == "git":
                return real_run(cmd, **kwargs)
            cwd = kwargs.get("cwd", ".")
            for arg in cmd:
                if arg.endswith(".py") and not arg.startswith("-"):
                    p = Path(cwd) / arg
                    if p.exists():
                        seen["content"] = p.read_text()
            return _mock_ruff_result()  # clean

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch("lint_check.subprocess.run", side_effect=_capture),
        ):
            staged_lint.staged_lint_gate(["app.py"], str(self.repo))

        self.assertEqual(
            seen.get("content"),
            "STAGED_CONTENT = 1\n",
            "the linter must READ the staged bytes off a real file, not the "
            "working tree and not a skipped/absent path",
        )


class TestMaterializeIsLanguageBlind(_StagedGitRepo):
    """AC4: materialization keys on the file's own directory + exact basename,
    the same table lookup for every language — no per-language branch."""

    def test_non_python_extension_materializes_identically(self) -> None:
        (self.repo / "main.go").write_bytes(b"package main\n")
        self._git("add", "main.go")

        temps, created, error = staged_lint._materialize_staged(
            str(self.repo), ["main.go"]
        )
        try:
            self.assertIsNone(error)
            self.assertEqual(created, [])
            self.assertEqual(len(temps), 1)
            tmp = Path(temps[0])
            self.assertEqual(
                tmp.name,
                "main.go",
                "EXACT basename preserved so filename-keyed linter rules match",
            )
            self.assertEqual(
                tmp.parent.parent,
                (self.repo / "main.go").parent,
                "temp lives in a subdir INSIDE the real parent, so config/"
                "toolchain walk-up resolves the same config (one extra hop)",
            )
            self.assertEqual(tmp.read_bytes(), b"package main\n", "staged bytes")
        finally:
            staged_lint._cleanup_temps(temps)
            staged_lint._cleanup_created_dirs(created)


class TestMaterializeCreatesMissingParentDir(_StagedGitRepo):
    """A staged-new file whose parent dir was removed in the working tree (index
    still carries the blob) must be materialized, not fail closed — the old
    `mkstemp(dir=<gone parent>)` raised FileNotFoundError and blocked the commit.
    The recreated dir is removed again so the working tree is left as it was.
    """

    def test_missing_parent_dir_is_recreated_then_cleaned(self) -> None:
        import shutil as sh

        sub = self.repo / "newpkg"
        sub.mkdir()
        (sub / "mod.go").write_bytes(b"package main\n")
        self._git("add", "newpkg/mod.go")
        sh.rmtree(sub)  # index keeps the blob; the working tree loses the dir
        self.assertFalse(sub.exists())

        temps, created, error = staged_lint._materialize_staged(
            str(self.repo), ["newpkg/mod.go"]
        )
        try:
            self.assertIsNone(
                error, "a gone parent dir must be recreated, not fail closed"
            )
            self.assertEqual(len(temps), 1)
            self.assertEqual(Path(temps[0]).name, "mod.go")
            self.assertEqual(Path(temps[0]).read_bytes(), b"package main\n")
            self.assertTrue(created, "the recreated dir must be tracked for cleanup")
        finally:
            staged_lint._cleanup_temps(temps)
            staged_lint._cleanup_created_dirs(created)

        self.assertFalse(sub.exists(), "the recreated parent dir must be removed again")


class TestGateFailsClosedOnBadMaterialize(_StagedGitRepo):
    """AC/robustness: an in-index file whose staged blob cannot be read is a bad
    read → unverified → BLOCK. Never a silent skip."""

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
        """The finding must name `app.py`, not the unlinked temp sibling — the
        agent is told to fix it, so the path it reads must be one that exists."""
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
        """The materialized siblings must not survive the gate — a crash-safe
        finally cleans them, and a clean run must too."""
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
    eslint filename globs, `__init__.py`/`conftest.py` special-cases) must still
    match the materialized file. A random temp NAME defeats those rules and turns
    a legitimate commit into a FALSE-POSITIVE block — the inverse of the
    documented fail-open. Materialization preserves the basename, so it matches.
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
class TestGateHandlesMissingParentDir(_StagedGitRepo):
    """A staged-new file whose parent dir is gone in the working tree (index
    still carries it) must not fail the gate closed — the old materialize raised
    on the missing dir and blocked a commit the `.exists()` predicate let through.
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


if __name__ == "__main__":
    unittest.main()
