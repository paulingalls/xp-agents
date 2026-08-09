#!/usr/bin/env python3
"""What the commit gate runs, and in what order.

Extracted from `test_dev_setup.py`, which owns a different question: whether
the gate EXISTS (`make setup`, `hooks_installed`, pyright config, the Makefile
target). These pins assume it exists and constrain its composition. The split
was forced by the 500-line cap — adding the ruff-autofix and staged-test pins
took that file to 504 — but the seam is the honest one, not the convenient one:
`test_dev_setup.py` answers "is the gate wired up", this answers "what does it
do when it fires".

The composition has two invariants, both learned the hard way:

- **Rewriters run before readers.** `ruff check --fix` and `ruff format` both
  rewrite staged files; pyright and the staged-test run read them. Order
  between the two rewriters is not arbitrary either — check --fix first, per
  ruff's own guidance, because a fix can leave code the formatter still has to
  tidy.
- **The commit gate is the CHEAP half.** The full suite lives on pre-push
  (measured 432s). What runs here is lint, types, and the test files you
  actually staged. Nothing here should ever be read as tree-wide coverage.

`test_lefthook_perf_gate.py` is the sibling for the pre-push side; it owns the
scale-timer tier and the alphabetical-ordering guarantee that keeps `perf` last.
This file borrows its `_hook`/`_command_body` helpers rather than re-parsing the
YAML, so a change to the parser cannot make one file's pins silently vacuous
while the other's still bite.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_lefthook_perf_gate import _command_body, _hook


class TestRewritersRunBeforeReaders(unittest.TestCase):
    def setUp(self):
        self.block = _hook("pre-commit")
        self.ruff_format = _command_body(self.block, "ruff-format")
        self.assertTrue(
            self.ruff_format, "pre-commit must define a ruff-format command"
        )

    def test_pre_commit_is_not_parallel(self):
        self.assertNotRegex(
            self.block,
            r"(?m)^\s+parallel:\s*true\b",
            "pre-commit must not be parallel: true — a concurrent ruff-format "
            "rewrite would race ruff-check/pyright/tests reading the same "
            "files mid-write.",
        )

    def test_pre_commit_is_piped(self):
        self.assertRegex(
            self.block,
            r"(?m)^\s+piped:\s*true\b",
            "pre-commit must be piped: true so nothing runs concurrently "
            "with ruff-format's rewrite.",
        )

    def test_ruff_format_runs_in_fix_mode(self):
        self.assertNotIn(
            "--check", self.ruff_format, "ruff-format must run in FIX mode"
        )
        self.assertRegex(
            self.ruff_format,
            r"run:\s*ruff format\b",
            "ruff-format command must invoke `ruff format`",
        )

    def test_ruff_format_stages_its_rewrite(self):
        self.assertRegex(
            self.ruff_format,
            r"(?m)^\s*stage_fixed:\s*true\b",
            "ruff-format in fix mode without stage_fixed leaves the rewrite "
            "unstaged — worse than the --check it replaces, since the "
            "commit then records unformatted content with no signal.",
        )

    def test_rewriters_are_sequenced_before_readers(self):
        """Both fix-mode commands run before anything that READS the files.

        Order between them is not arbitrary: ruff's own guidance is check --fix
        FIRST, because a fix can leave code the formatter still has to tidy.
        Reverse them and a commit records unformatted output from an autofix.
        """
        ruff_check = _command_body(self.block, "ruff-check")
        self.assertRegex(
            ruff_check,
            r"(?m)^\s*priority:\s*1\b",
            "ruff-check must set priority: 1 — it rewrites in --fix mode and "
            "its output still has to pass through the formatter.",
        )
        self.assertRegex(
            self.ruff_format,
            r"(?m)^\s*priority:\s*2\b",
            "ruff-format must set priority: 2 — after ruff-check --fix, "
            "before every command that reads the files.",
        )

    def test_ruff_check_fixes_and_stages(self):
        """A lint error a machine can fix should not cost a failed commit.

        Without stage_fixed the fix lands in the working tree and the commit
        records the unfixed content — the same trap ruff-format's own
        stage_fixed pin exists to close.
        """
        ruff_check = _command_body(self.block, "ruff-check")
        self.assertRegex(
            ruff_check, r"run:\s*ruff check --fix\b", "ruff-check must pass --fix"
        )
        self.assertRegex(
            ruff_check,
            r"(?m)^\s*stage_fixed:\s*true\b",
            "ruff-check --fix without stage_fixed leaves the fix unstaged",
        )


class TestStagedTestsRunOnTheCommitGate(unittest.TestCase):
    """The commit gate runs the tests you actually touched, never the suite.

    If you staged a test file, it runs, so breaking the test you just wrote is
    caught now rather than at story close. It proves nothing about the rest of
    the tree — that is push's job, and this pin must not be read as coverage.
    """

    def setUp(self):
        self.block = _hook("pre-commit")
        self.cmd = _command_body(self.block, "staged-tests")
        self.assertTrue(self.cmd, "pre-commit must define a staged-tests command")

    def test_bails_when_no_test_file_survives_the_filter(self):
        """The trap this guards: a DELETED staged test file.

        Filtering to existing paths can yield an EMPTY list, and `pytest` with
        no arguments collects the WHOLE tree — turning the cheap gate back into
        the 432s run this change just removed. The command must test for empty
        and skip, never fall through to a bare `pytest`.
        """
        self.assertRegex(
            self.cmd,
            r'-z\s*"?\$\{?files',
            "staged-tests must bail on an empty file list — a bare `pytest` "
            "with no paths runs the entire suite.",
        )
        self.assertIn(
            "-f",
            self.cmd,
            "staged-tests must filter to files that still exist, so a deleted "
            "test file cannot fail the commit with a collection error.",
        )

    def test_glob_reaches_test_files_directly_under_tests(self):
        """`tests/**/test_*.py` would silently skip the top-level pins.

        lefthook's `**` requires at least one directory, so the narrower glob
        matched tests/skills/... and ran 11 tests while a staged
        tests/test_dev_setup.py was never collected. Measured, not reasoned —
        and it matters because the cross-cutting pins live at that top level.
        """
        self.assertNotRegex(
            self.cmd,
            r"glob:.*tests/\*\*/test_",
            "staged-tests glob must not require a subdirectory under tests/ — "
            "use **/test_*.py so top-level test files are collected too.",
        )

    def test_strips_xp_perf(self):
        """A developer with XP_PERF=1 exported who stages a scale test would
        otherwise arm wall-clock benchmarks inside the commit gate, where they
        fail on timing noise. The pre-push side of the same property lives in
        `test_lefthook_perf_gate.py`; this leg is what keeps the commit gate's
        own run covered after the suite moved off it."""
        self.assertIn(
            "-u XP_PERF",
            self.cmd,
            "staged-tests must env -u XP_PERF",
        )

    def test_does_not_run_the_whole_suite(self):
        self.assertNotRegex(
            self.cmd,
            r"pytest\s+-n\s+auto\s*$",
            "staged-tests must not run the full suite — that is pre-push's job",
        )


if __name__ == "__main__":
    unittest.main()
