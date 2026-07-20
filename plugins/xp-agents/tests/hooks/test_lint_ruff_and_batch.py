#!/usr/bin/env python3
"""Tests for lint_check.py's low-level linter-invocation functions.

Split from test_lint.py to keep files under the 500-line cap: run_ruff (the
single source of truth for EDIT-time ruff invocation) and run_linter_batch
(the commit-gate's single-fork-over-multiple-paths runner).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lint_check
from conftest import _HookTestCase, _mock_ruff_result

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


if __name__ == "__main__":
    unittest.main()
