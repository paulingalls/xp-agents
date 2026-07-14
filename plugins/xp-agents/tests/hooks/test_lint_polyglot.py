#!/usr/bin/env python3
"""What the REAL polyglot linters do — and what our gate must therefore encode.

v4.8.0's headline claims the commit-time lint gate "enforces in ANY language". It
does not: C/C++ and Java are parked in the degraded set, so they are not gated at
all. This suite is what un-parking has to survive.

WHY REAL BINARIES, AND NOT A STUB. A hand-written fake `clang-tidy` encodes the
AUTHOR'S MODEL of the CLI, so it cannot fail in the one way that matters -- the
model being wrong. If the author assumes clang-tidy exits 1 on findings, the stub
exits 1, the gate blocks, the suite is green, and PRODUCTION FALSE-CLEANS. That is
the very bug being fixed, wearing a green badge, and it is worse than an honest skip:
a skip reads as "not proven", while a stub's green bar reads as end-to-end evidence.
It is also how story-007 shipped a dead gate -- its fixture was single-line and
production's command was not.

So these tests ask the binary. They are also a TRIPWIRE: if a future clang-tidy
changes its CLI, they go red and we find out. A stub could never do that.

THE FOUR FACTS, measured (clang-tidy 22.1.8, checkstyle 13.8.0):

  1. The CORRECT argv (`clang-tidy app.c --`) FINDS the violation and EXITS 0.
     Fixing the argv ALONE would therefore CREATE a true false-clean. It needs
     `--warnings-as-errors`.
  2. A TRAILING `--` means "no compiler flags" and OVERRIDES compile_commands.json,
     so the include path is lost. Debt 1fc4a26c846a's own prescription -- "sources
     before the separator, TRAILING --" -- is refuted by its second half.
  3. Without a compile DB, a file needing an `-I` fails to compile ->
     clang-diagnostic-error -> non-zero + output -> the gate would BLOCK on an error
     the committer cannot fix by fixing their diff. So C/C++ is gatable only WITH a
     compile DB.
  4. checkstyle's exit code counts severity=ERROR only. A severity=WARNING violation
     PRINTS and exits 0, and its CLI has no warnings-as-errors lever. Java's exit
     code cannot express the gate's contract, so Java stays DEGRADED -- honestly,
     rather than gated in name only.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import linters


def _usable(binary: str) -> str | None:
    """The path to `binary`, but ONLY if it actually runs.

    On PATH is not the same as functional, and the difference is not academic:
    checkstyle is a JVM launcher, and under a too-old JDK it is on PATH and throws
    `LinkageError` before it can lint a thing. A guard that asked only `which` would
    have run these tests against a binary that cannot start — and, worse, the same
    confusion lives in PRODUCTION: a crashing checkstyle exits non-zero WITH output,
    which the gate's contract reads as FINDINGS. "Cannot start" and "found
    violations" are indistinguishable by exit code alone.
    """
    path = shutil.which(binary)
    if not path:
        return None
    try:
        probe = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return path if probe.returncode == 0 else None


_CLANG_TIDY = _usable("clang-tidy")
_CHECKSTYLE = _usable("checkstyle")
_CLANG_FORMAT = _usable("clang-format")

# `skipUnless` guards every use at runtime, but pyright cannot see through a class
# decorator — so narrow to `str` here. The fallback name is never invoked: the class
# is skipped whenever the probe above came back None.
CLANG_TIDY: str = _CLANG_TIDY or "clang-tidy"
CHECKSTYLE: str = _CHECKSTYLE or "checkstyle"
CLANG_FORMAT: str = _CLANG_FORMAT or "clang-format"

# A check with no compiler-flag dependency, so the finding is about the CODE and not
# about the build. Braces-around-statements fires on a one-line `if`.
_CLANG_TIDY_CONFIG = "Checks: '-*,readability-braces-around-statements'\n"
_DIRTY_C = "int main(void) {\n    if (1) return 0;\n    return 1;\n}\n"
_CLEAN_C = "int main(void) {\n    return 0;\n}\n"


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=60
    )


class _TmpProject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)


@unittest.skipUnless(_CLANG_TIDY, "clang-tidy not installed")
class TestWhatClangTidyActuallyDoes(_TmpProject):
    """The facts our argv column encodes. If these go red, the CLI changed."""

    def setUp(self):
        super().setUp()
        (self.d / ".clang-tidy").write_text(_CLANG_TIDY_CONFIG)
        (self.d / "app.c").write_text(_DIRTY_C)

    def test_correct_argv_finds_the_violation_but_EXITS_ZERO(self):
        """FACT 1, and the reason the obvious fix is a trap.

        Sources before the separator is the right shape -- and on its own it makes
        things WORSE. clang-tidy lints the file correctly, prints the finding, and
        exits 0, which our exit-code contract reads as CLEAN. The gate would report
        clean on a file it had just found a violation in.
        """
        r = _run([CLANG_TIDY, "app.c", "--"], self.d)

        self.assertIn("readability-braces", r.stdout)
        self.assertEqual(r.returncode, 0, "a fix that stops here ships a false-clean")

    def test_warnings_as_errors_is_what_makes_the_exit_code_honest(self):
        """FACT 1's fix: a strictness flag -- a structural table row. It is in
        `--help`, and it says BE STRICT without encoding what any rule means."""
        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "app.c", "--"], self.d)

        self.assertIn("readability-braces", r.stdout)
        self.assertNotEqual(r.returncode, 0, "now a finding can block")

    def test_a_clean_file_still_exits_zero(self):
        """The control. A strictness flag that blocked everything would be useless."""
        (self.d / "app.c").write_text(_CLEAN_C)

        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "app.c", "--"], self.d)

        self.assertEqual(r.returncode, 0)

    def test_the_SHIPPED_argv_lints_zero_sources(self):
        """The bug, pinned against the BINARY rather than against our own argv --
        asserting it against our code would be a tautology.

        `clang-tidy -- app.c` reads app.c as a COMPILER FLAG, not a source, because
        everything after the separator is compiler flags. Note the debt calls this a
        "silent false-clean". It is not: it errors with "no input files".
        """
        r = _run([CLANG_TIDY, "--", "app.c"], self.d)

        self.assertIn("no input files", (r.stderr + r.stdout).lower())
        self.assertNotIn("readability-braces", r.stdout, "it linted NOTHING")


@unittest.skipUnless(_CLANG_TIDY, "clang-tidy not installed")
class TestTheCompileDatabaseDecidesWhetherCppIsGatable(_TmpProject):
    """FACTS 2 and 3 -- why the gate needs a compile-DB precondition."""

    def setUp(self):
        super().setUp()
        (self.d / ".clang-tidy").write_text(_CLANG_TIDY_CONFIG)
        (self.d / "inc").mkdir()
        (self.d / "inc" / "hdr.h").write_text("#define ANSWER 42\n")
        (self.d / "needs_inc.c").write_text(
            '#include "hdr.h"\nint main(void){ if (ANSWER) return 0; return 1; }\n'
        )

    def _write_compile_db(self) -> None:
        (self.d / "compile_commands.json").write_text(
            json.dumps(
                [
                    {
                        "directory": str(self.d),
                        "command": "cc -Iinc -c needs_inc.c",
                        "file": str(self.d / "needs_inc.c"),
                    }
                ]
            )
        )

    def test_with_a_compile_db_and_NO_trailing_separator_it_lints_correctly(self):
        """The shape the gate must build when a compile DB exists."""
        self._write_compile_db()

        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "needs_inc.c"], self.d)

        self.assertIn("readability-braces", r.stdout, "it found the REAL finding")
        self.assertNotIn("file not found", r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0)

    def test_a_trailing_separator_OVERRIDES_the_compile_db(self):
        """FACT 2 -- the half of debt 1fc4a26c846a's prescription that is WRONG.

        The debt says "sources before the separator, trailing --". The trailing `--`
        means "no compiler flags", which overrides the database: the include path is
        lost and clang-tidy cannot compile the file at all.
        """
        self._write_compile_db()

        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "needs_inc.c", "--"], self.d)

        self.assertIn("file not found", r.stdout + r.stderr)

    def test_without_a_compile_db_a_file_needing_an_include_CANNOT_be_gated(self):
        """FACT 3 -- the unfixable gate, which is why no-DB must DEGRADE.

        clang-diagnostic-error is non-zero WITH output, which our contract reads as
        FINDINGS. Blocking here would refuse a commit over a header path the
        committer cannot fix by fixing their diff -- and the first thing anyone does
        with an unfixable gate is disable it.
        """
        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "needs_inc.c", "--"], self.d)

        self.assertIn("file not found", r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0, "it would BLOCK, and no diff fixes it")


@unittest.skipUnless(_CLANG_FORMAT, "clang-format not installed")
class TestClangFormatDoesNotShareClangTidysSeparatorBug(_TmpProject):
    """The row that is GATED in C/C++ today, and was pinned by NOTHING.

    clang-tidy's separator bug is easy to over-generalise to its sibling: same LLVM
    release, same `clang-` prefix, adjacent rows in every table here. If clang-format
    read a trailing `-- app.c` as a compiler flag the way clang-tidy does, the DEFAULT
    argv shape would lint zero sources in every C/C++ repo that has a `.clang-format`
    and no `.clang-tidy` — the same false-clean, in a row nobody thought to check.

    It does NOT: clang-format is an ordinary LLVM `cl` binary, not a ClangTool, so `--`
    means "end of options" and the path after it is a PATH. That is a fact about a
    binary, so it is asked of the binary. The two rows differ, and the shape column is
    right to carry only one of them — this is the evidence for the row that ISN'T there.
    """

    _DIRTY_C = "int main(void){\n  if(1)return 0;\n      return   1;\n}\n"
    _CLEAN_C = "int main(void) { return 0; }\n"

    def setUp(self):
        super().setUp()
        (self.d / ".clang-format").write_text("BasedOnStyle: LLVM\n")

    def _shipped_argv(self, path: str) -> list[str]:
        """The argv `linter_argv` builds for clang-format: the DEFAULT shape."""
        return [CLANG_FORMAT, "--dry-run", "-Werror", "--", path]

    def test_the_separator_is_read_as_end_of_options_not_as_compiler_flags(self):
        (self.d / "app.c").write_text(self._DIRTY_C)

        r = _run(self._shipped_argv("app.c"), self.d)

        self.assertIn("clang-format-violations", r.stderr, "it LINTED the file")
        self.assertNotIn("no input files", (r.stdout + r.stderr).lower())
        self.assertNotEqual(r.returncode, 0, "and a finding can block")

    def test_a_clean_file_exits_zero(self):
        """The control: -Werror must not block everything."""
        (self.d / "app.c").write_text(self._CLEAN_C)

        r = _run(self._shipped_argv("app.c"), self.d)

        self.assertEqual(r.returncode, 0)


@unittest.skipUnless(_CLANG_TIDY, "clang-tidy not installed")
class TestAPartialCompileDatabaseMustNotBlock(_TmpProject):
    """A compile DB that EXISTS is not a compile DB that COVERS the staged file.

    Found in review, and it is a block this story ITSELF introduced. The first
    precondition asked "is compile_commands.json at the git root?" — but gatability
    needs "can clang-tidy COMPILE this staged file?", and those come apart exactly
    where it hurts: a partial or stale DB (covers src/, staged file under tests/) has
    the file's headers nowhere, so clang-tidy cannot compile it:

        tests/t.c:1:10: error: 't.h' file not found [clang-diagnostic-error]

    Non-zero, WITH output — which the contract reads as FINDINGS. The gate refuses the
    commit, and nothing in the diff fixes it: you have to regenerate the compile
    database, which is a build step. Partial DBs are the ordinary case (a new file, a
    test subtree, generated sources, a DB nobody re-ran).

    Before this story clang-tidy was degraded unconditionally, so the block is NEW —
    the unfixable gate the whole degrade doctrine exists to prevent, reintroduced by
    the fix for it. Coverage is therefore tested PER FILE, and an uncovered file
    DEGRADES. Erring toward advisory loses a little coverage; erring the other way
    hands users a gate they can only escape by turning it off.
    """

    def setUp(self):
        super().setUp()
        (self.d / ".clang-tidy").write_text(_CLANG_TIDY_CONFIG)
        # TWO include trees. The database's one entry reaches a_inc; nothing tells
        # clang-tidy about b_inc. That distinction is the whole finding, and I got it
        # wrong the first time: clang-tidy INFERS a command for an uncovered file from
        # the database's nearest entry, so an uncovered file whose header those
        # inferred flags happen to reach lints perfectly well. The block appears only
        # when the inferred flags do NOT reach it — which is the ordinary shape of a
        # stale database (a new subtree with its own include path).
        for d in ("a_inc", "b_inc", "src", "tests"):
            (self.d / d).mkdir()
        (self.d / "a_inc" / "a.h").write_text("#define A 1\n")
        (self.d / "b_inc" / "b.h").write_text("#define B 1\n")
        (self.d / "src" / "covered.c").write_text(
            '#include "a.h"\nint main(void){ if (A) return 0; return 1; }\n'
        )
        (self.d / "tests" / "t.c").write_text(
            '#include "b.h"\nint other(void){ if (B) return 0; return 1; }\n'
        )
        (self.d / "compile_commands.json").write_text(
            json.dumps(
                [
                    {
                        "directory": str(self.d),
                        "command": "cc -Ia_inc -c src/covered.c",
                        "file": str(self.d / "src" / "covered.c"),
                    }
                ]
            )
        )

    def test_the_binary_really_does_fail_on_an_uncovered_file(self):
        """The fact, from the binary — not from our model of it. This is precisely
        what the gate would have blocked on, and it is why coverage has to be tested
        rather than assumed from the database's mere existence."""
        r = _run([CLANG_TIDY, "--warnings-as-errors=*", "tests/t.c"], self.d)

        self.assertIn("file not found", r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, 0, "non-zero + output reads as FINDINGS")

    def test_an_uncovered_file_degrades_instead_of_blocking(self):
        """So the gate must not even try. Degrade, and say why."""
        self.assertFalse(
            linters.is_file_scoped("clang-tidy", str(self.d), ["tests/t.c"]),
            "an uncovered file must DEGRADE — a block here is unfixable by any diff",
        )
        self.assertIsNone(
            linters.linter_argv("clang-tidy", ["tests/t.c"], root=str(self.d)),
            "and it must not be invoked at all",
        )

    def test_a_covered_file_is_still_gated(self):
        """The control. Degrading uncovered files must not degrade EVERY file, or the
        C/C++ gate is back to doing nothing."""
        self.assertTrue(
            linters.is_file_scoped("clang-tidy", str(self.d), ["src/covered.c"]),
            "a file the DB covers is genuinely gatable",
        )

    def test_a_new_file_beside_a_covered_one_is_still_gated(self):
        """clang-tidy INFERS a command for a file the DB does not name, from its
        siblings — so a strict name-match would degrade every newly-added source and
        quietly hand C/C++ back its old non-gate. Coverage is by DIRECTORY."""
        (self.d / "src" / "brand_new.c").write_text(_DIRTY_C)

        self.assertTrue(
            linters.is_file_scoped("clang-tidy", str(self.d), ["src/brand_new.c"]),
        )


@unittest.skipUnless(_CHECKSTYLE, "checkstyle not installed")
class TestCheckstyleCannotExpressTheContract(_TmpProject):
    """FACT 4 -- why Java stays degraded rather than gated in name only."""

    _RULE = """<?xml version="1.0"?>
<!DOCTYPE module PUBLIC "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
  "https://checkstyle.org/dtds/configuration_1_3.dtd">
<module name="Checker">
  <property name="severity" value="{severity}"/>
  <module name="TreeWalker"><module name="UnusedImports"/></module>
</module>
"""
    _DIRTY_JAVA = (
        "import java.util.List;\n"
        "public class Foo { public static void main(String[] a){ "
        "System.out.println(1); } }\n"
    )

    def setUp(self):
        super().setUp()
        (self.d / "Foo.java").write_text(self._DIRTY_JAVA)

    def _cfg(self, severity: str) -> str:
        p = self.d / f"{severity}.xml"
        p.write_text(self._RULE.format(severity=severity))
        return str(p)

    def test_a_severity_error_violation_exits_non_zero(self):
        """The only case checkstyle CAN express."""
        r = _run([CHECKSTYLE, "-c", self._cfg("error"), "Foo.java"], self.d)

        self.assertIn("UnusedImports", r.stdout)
        self.assertNotEqual(r.returncode, 0)

    def test_a_severity_WARNING_violation_prints_and_EXITS_ZERO(self):
        """THE FALSE-CLEAN, and why Java cannot be gated on the exit code.

        The SAME violation, at warning severity, is reported and then exits 0. Our
        contract reads that as CLEAN. Nothing in checkstyle's CLI changes it: the
        options are -b -c -d -e -E -f -g -G -h -j -J -o -p -s -t -T -V -w -x, and
        `-w` is TAB WIDTH. There is no warnings-as-errors lever.

        Gating Java would mean PARSING checkstyle's report to count violations -- and
        "the parser WAS the bug" (story-005). So Java stays degraded, and the release
        note stops claiming otherwise.
        """
        r = _run([CHECKSTYLE, "-c", self._cfg("warning"), "Foo.java"], self.d)

        self.assertIn("UnusedImports", r.stdout, "it FOUND the violation")
        self.assertEqual(r.returncode, 0, "and reported success anyway")


if __name__ == "__main__":
    unittest.main()
