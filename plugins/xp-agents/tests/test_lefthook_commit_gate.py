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

from _paths import _SCRIPTS_DIR
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

        lefthook's `**` requires at least one directory, so that narrower glob
        matched tests/skills/... and ran 11 tests while a staged
        tests/test_dev_setup.py was never collected. Measured, not reasoned.

        The current glob is wider still — `**/*.py`, with the BODY doing the
        classifying — because shared fixtures carry no `test_` in their names.
        Pinned positively as well as negatively: a regex that only forbade the
        old form went vacuous the moment the glob widened, so narrowing it back
        would have passed green while silently dropping fixture coverage.
        """
        self.assertNotRegex(
            self.cmd,
            r"glob:.*tests/\*\*/test_",
            "staged-tests glob must not require a subdirectory under tests/",
        )
        self.assertRegex(
            self.cmd,
            r'glob:.*"\*\*/\*\.py"',
            "staged-tests must glob every .py and classify in the body — a "
            "test_*-only glob cannot see conftest.py or the _*.py helpers.",
        )
        self.assertRegex(
            self.cmd,
            r'glob:.*"\*\*/\*\.js"',
            "staged-tests must also glob .js — the shipped workflow script and "
            "its harness are the only JavaScript in the tree, and no linter, "
            "formatter or type checker in this file reads one, so without this "
            "a staged .js runs nothing until push.",
        )

    def test_tolerates_an_empty_collection(self):
        """pytest exits 5 on "no tests collected", which lefthook reads as a
        failed commit. A directory target can legitimately contain none (a new
        package, one emptied by a rename), so the exit must be tolerated or the
        gate refuses commits for the very reason it was fixed."""
        self.assertRegex(
            self.cmd,
            r"\|\|\s*\[\s*\$\?\s*-eq\s*5\s*\]",
            "staged-tests must tolerate pytest's exit 5",
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


def _shell_body(cmd: str) -> str:
    """Just the shell, without the YAML that carries it.

    `_command_body` returns every indented line under `staged-tests:`, which
    includes `glob:` and `run: |`. Handing those to `sh -c` made it report
    "glob:: command not found" and — because `run: |` ends in a pipe — turned
    the body's first real statement into the right half of a pipeline, where
    its assignment was lost to a subshell. The tests passed only because the
    variable happened to be unset, so the harness was not executing what
    lefthook executes.
    """
    lines = cmd.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("run:"):
            return "\n".join(lines[i + 1 :])
    return cmd


def _execute_gate(cmd: str, staged: list[str], tmp: Path) -> tuple[list[str], int]:
    """Run the gate's shell body for real; return (argv pytest received, rc).

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
    body = _shell_body(cmd).replace("{staged_files}", " ".join(staged))
    proc = subprocess.run(
        ["sh", "-c", body], cwd=REPO_ROOT, env=env, capture_output=True, text=True
    )
    argv = (
        [line for line in argv_log.read_text().splitlines() if line]
        if argv_log.exists()
        else []
    )
    return argv, proc.returncode


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
        argv, rc = _execute_gate(
            self.cmd, ["plugins/xp-agents/scripts/test_parsing.py"], self.tmp
        )
        self.assertEqual(
            argv, [], "a production module must not become a pytest target"
        )
        # The reported symptom was "the commit is refused", which argv alone
        # does not cover: a body that runs nothing but exits non-zero blocks
        # every commit exactly as before.
        self.assertEqual(rc, 0, "the gate must not refuse the commit")

    def test_a_staged_workflow_js_runs_the_module_that_drives_node(self):
        """The `.js` branch, EXECUTED. Its only coverage was a regex over the
        glob line, which cannot tell a `case` pattern that fires from one that
        never does — the failure this whole class exists for, and the sibling
        branches all have an execution test. Found by the broad review.

        The mapping matters: JS maps to the pytest module that shells out to
        `node --test`, not to node directly, because that module carries the
        non-vacuity floor and `node --test` on a glob matching nothing exits 0.
        """
        argv, rc = _execute_gate(
            self.cmd, ["plugins/xp-agents/workflows/code_review.js"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/test_workflow_js_suite.py", argv)
        self.assertEqual(rc, 0)

    def test_a_staged_js_test_maps_to_the_same_driver_once(self):
        """Both JavaScript locations map to one driver, and staging both must
        not run it twice — the body dedupes, and nothing asserted that."""
        argv, _ = _execute_gate(
            self.cmd,
            [
                "plugins/xp-agents/workflows/code_review.js",
                "plugins/xp-agents/tests/workflows/code_review_test.js",
            ],
            self.tmp,
        )
        driver = "plugins/xp-agents/tests/test_workflow_js_suite.py"
        self.assertEqual(argv.count(driver), 1, f"argv: {argv}")

    def test_an_unrelated_js_file_is_not_a_test_target(self):
        """Non-vacuity for the pair above: the branch is scoped to the two
        JavaScript locations, so a `.js` anywhere else must select nothing
        rather than mapping to the driver by accident."""
        argv, rc = _execute_gate(self.cmd, ["docs/example.js"], self.tmp)
        self.assertEqual(argv, [])
        self.assertEqual(rc, 0)

    def test_real_test_file_still_runs(self):
        argv, _ = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_dev_setup.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/test_dev_setup.py", argv)

    def test_shared_fixture_selects_its_directory_in_parallel(self):
        """Editing conftest.py can break thousands of tests, and matched no
        glob — so it ran ZERO of them and committed green."""
        argv, _ = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/conftest.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests", argv)
        self.assertIn("-n", argv)
        self.assertIn("auto", argv)

    def test_nested_fixture_selects_only_its_own_directory(self):
        argv, _ = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/hooks/_commit_helpers.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/hooks", argv)
        self.assertNotIn("plugins/xp-agents/tests", argv)

    def test_fixture_and_a_test_inside_it_do_not_both_become_targets(self):
        """pytest handed both a directory and a file inside it double-collects."""
        argv, _ = _execute_gate(
            self.cmd,
            [
                "plugins/xp-agents/tests/hooks/_commit_helpers.py",
                "plugins/xp-agents/tests/hooks/test_bash.py",
            ],
            self.tmp,
        )
        self.assertIn("plugins/xp-agents/tests/hooks", argv)
        self.assertNotIn("plugins/xp-agents/tests/hooks/test_bash.py", argv)

    def test_helper_that_is_not_conftest_or_underscore_selects_its_directory(self):
        """tests/engine/sister_test_base.py defines a base class and no
        test_* functions. An earlier catch-all made it a bare file target,
        where pytest collects nothing and exits 5 and lefthook refuses the
        commit — the same defect this command fixes for scripts/test_parsing.py,
        one directory over. Only test_*.py is a file; every other .py in the
        tests tree is a helper."""
        argv, rc = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/engine/sister_test_base.py"], self.tmp
        )
        self.assertIn("plugins/xp-agents/tests/engine", argv)
        self.assertNotIn("plugins/xp-agents/tests/engine/sister_test_base.py", argv)
        self.assertEqual(rc, 0)

    def test_file_only_selection_stays_sequential(self):
        """-n auto is for directory targets. Spawning xdist workers to run one
        file costs more than it saves, and the commit gate's whole point is
        being cheap enough to pay on every increment."""
        argv, _ = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_dev_setup.py"], self.tmp
        )
        self.assertNotIn("-n", argv)

    def test_deleted_staged_file_still_bails(self):
        argv, rc = _execute_gate(
            self.cmd, ["plugins/xp-agents/tests/test_gone_forever.py"], self.tmp
        )
        self.assertEqual(argv, [])
        self.assertEqual(rc, 0, "a deleted staged test must not refuse the commit")


class TestDerivedManifestsAreRegeneratedOnCommit(unittest.TestCase):
    """Something must RUN the emitters, or the derived manifests rot.

    Both derived packaging manifests are generated from a hand-edited source,
    and both had regeneration pins from the day they landed — but those pins run
    in the full suite, which is PUSH. Between a version bump and the next push
    the tree shipped a desynchronized pair, and the repair cost two commits in
    one day. Nothing referenced either emitter: not the Makefile, not lefthook,
    not the release docs, only the modules' own docstrings.

    The Makefile half is pinned here rather than in `test_dev_setup.py`, which
    owns whether the gate exists at all: this target exists to serve this gate,
    and splitting the two halves across files is how one gets edited without the
    other.
    """

    MAKEFILE = REPO_ROOT / "Makefile"
    DERIVED = (
        "plugins/xp-agents/hooks/hooks.codex.json",
        "plugins/xp-agents/.codex-plugin/plugin.json",
    )

    def setUp(self):
        self.cmd = _command_body(_hook("pre-commit"), "derived-manifests")
        self.assertTrue(self.cmd, "pre-commit must define a derived-manifests command")
        self.makefile = self.MAKEFILE.read_text(encoding="utf-8")

    def test_the_gate_regenerates_through_the_make_target(self):
        self.assertIn(
            "make manifests",
            self.cmd,
            "the gate must call the same target a human does — two spellings of "
            "the regeneration drift apart, and only one of them is documented",
        )

    def test_the_gate_stages_every_derived_manifest(self):
        for path in self.DERIVED:
            with self.subTest(path=path):
                self.assertIn(
                    path,
                    self.cmd,
                    "regenerating without staging records the stale copy in the "
                    "commit and leaves the fresh one loose in the working tree",
                )

    def test_the_make_target_is_declared_phony(self):
        """A file named `manifests` would otherwise make the target a no-op."""
        phony = [
            line for line in self.makefile.splitlines() if line.startswith(".PHONY:")
        ]
        self.assertTrue(
            any("manifests" in line for line in phony),
            f".PHONY must list `manifests`; found {phony}",
        )

    def test_every_emitter_script_is_wired_into_the_target(self):
        """The roster is derived, not typed: a third emitter is covered the day
        it lands rather than silently left unrun, which is exactly the state
        both of today's emitters shipped in.

        Derived from the `default_out_dir` CLI contract the packaging emitters
        share, not from the `*_emit.py` name — `commit_emit.py` appends a runtime
        event and generates no artifact, so the name alone selects the wrong set.
        """
        body = self.makefile.split("manifests:", 1)[1].split("\n\n", 1)[0]
        emitters = sorted(
            path.name
            for path in _SCRIPTS_DIR.glob("*.py")
            if "def default_out_dir(" in path.read_text(encoding="utf-8")
        )
        self.assertTrue(emitters, "no emitter scripts found — the contract moved")
        missing = [name for name in emitters if name not in body]
        self.assertEqual(
            missing,
            [],
            f"`make manifests` never runs {missing}, so whatever they generate "
            "desynchronizes until the full suite runs at push",
        )


if __name__ == "__main__":
    unittest.main()
