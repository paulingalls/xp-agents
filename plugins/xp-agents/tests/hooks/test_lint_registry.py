#!/usr/bin/env python3
"""Structural pins over linters.py's registry tables.

Split from test_lint.py to keep files under the 500-line cap: these tests
never invoke a linter subprocess — they only assert the sparse-matrix columns
(LINTER_STDIN_SHAPES, LINTER_COMMANDS, DEGRADED_LINTERS, ...) stay internally
consistent and in sync with each other.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import linters

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


if __name__ == "__main__":
    unittest.main()
