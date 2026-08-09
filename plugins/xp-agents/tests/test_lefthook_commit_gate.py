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

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_lefthook_perf_gate import REPO_ROOT, _command_body, _hook


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

    def test_never_a_bare_whole_tree_pytest(self):
        """A literal tree path on the pytest line would restore the full run.

        Renamed from `test_does_not_run_the_whole_suite`, whose regex forbade
        `pytest -n auto` — the CHEAP spelling. Once a directory target exists
        the sequential run is the dangerous one (the recorded 432s), so that
        form pinned the wrong half. The real invariant is behavioral and lives
        in TestGateSelectsTheRightTargets, which executes the body and asserts
        on the argv pytest receives.
        """
        self.assertNotRegex(
            self.cmd,
            r"pytest\s+plugins/xp-agents/tests\b",
            "staged-tests must never name the tree literally — targets are "
            "derived from staged files",
        )


def _execute_gate(cmd: str, staged: list[str], tmp: Path) -> list[str]:
    """Run the gate's shell body for real; return the argv pytest received.

    The rest of this file pins lefthook.yml as TEXT, which cannot distinguish
    a filter that works from one that never fires — a wrong `case` pattern, a
    mapping eaten by the `-f` guard, or a mistyped prefix all leave the same
    string in the file. So this substitutes `{staged_files}`, puts a stub
    `pytest` on PATH that records its arguments, and asserts on what the
    command actually decided to run.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    argv_log = tmp / "argv.txt"
    stub = bin_dir / "pytest"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{argv_log}"\n')
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    subprocess.run(
        ["sh", "-c", cmd.replace("{staged_files}", " ".join(staged))],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line]


class TestGateSelectsTheRightTargets(unittest.TestCase):
    """What the command DOES, not what lefthook.yml says."""

    def setUp(self):
        self.cmd = _command_body(_hook("pre-commit"), "staged-tests")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_production_module_named_like_a_test_runs_nothing(self):
        """scripts/test_parsing.py is SHIPPED code, not a test.

        pytest collects nothing there and exits 5, which lefthook reads as
        failure — so staging it alone refused the commit outright. Verified:
        `pytest plugins/xp-agents/scripts/test_parsing.py -q` → no tests ran.
        """
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/scripts/test_parsing.py"], self.tmp
        )
        self.assertEqual(
            argv, [], "a production module must not become a pytest target"
        )

    def test_real_test_file_still_runs(self):
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_dev_setup.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/test_dev_setup.py", argv)

    def test_shared_fixture_selects_its_directory_in_parallel(self):
        """Editing conftest.py can break thousands of tests, and matched no
        glob — so it ran ZERO of them and committed green."""
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/conftest.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests", argv)
        self.assertIn("-n", argv)
        self.assertIn("auto", argv)

    def test_nested_fixture_selects_only_its_own_directory(self):
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/hooks/_commit_helpers.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/hooks", argv)
        self.assertNotIn("plugins/xp-agents/tests", argv)

    def test_fixture_and_a_test_inside_it_do_not_both_become_targets(self):
        """pytest handed both a directory and a file inside it double-collects."""
        argv = _execute_gate(
            self.cmd,
            [
                "plugins/xp-agents/tests/hooks/_commit_helpers.py",
                "plugins/xp-agents/tests/hooks/test_bash.py",
            ],
            self.tmp,
        )
        self.assertIn("plugins/xp-agents/tests/hooks", argv)
        self.assertNotIn("plugins/xp-agents/tests/hooks/test_bash.py", argv)

    def test_file_only_selection_stays_sequential(self):
        """-n auto is for directory targets. Spawning xdist workers to run one
        file costs more than it saves, and the commit gate's whole point is
        being cheap enough to pay on every increment."""
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_dev_setup.py"], self.tmp
        )
        self.assertNotIn("-n", argv)

    def test_deleted_staged_file_still_bails(self):
        argv = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_gone_forever.py"], self.tmp
        )
        self.assertEqual(argv, [])


if __name__ == "__main__":
    unittest.main()
