#!/usr/bin/env python3
"""The compile-database precondition, proved against the real clang-tidy.

Split from test_lint_polyglot at the commit that pushed it past the 500-line cap.
That suite asks what the BINARIES do; this one asks what OUR GATE does with a compile
database — a different question, and the one where C/C++ gets an UNFIXABLE block wrong
twice over:

  * COVERAGE — a database that EXISTS is not a database that COVERS the staged file.
    An uncovered file cannot be compiled, so clang-tidy errors, and the exit-code
    contract reads that as findings. Nothing in the diff fixes it: you have to
    regenerate the database, which is a build step. So it must DEGRADE.
  * THE BASE the paths resolve against — the database sits at the git ROOT, but the
    linter runs from its CONFIG dir, so its paths are relative to THAT. Conflate them
    and a perfectly-covered file is refused, which fails CLOSED and blocks every
    commit in the ordinary root-DB/subdir-config layout.

Both are asked of the binary, never of a stub: a stub encodes the author's model of
the CLI, so it cannot fail in the one way that matters — the model being wrong.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import lint_check
import linters
import staged_lint
from _lint_binaries import (
    _CLANG_TIDY,
    _CLANG_TIDY_CONFIG,
    _DIRTY_C,
    CLANG_TIDY,
    _run,
    _TmpProject,
)


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


@unittest.skipUnless(_CLANG_TIDY, "clang-tidy not installed")
class TestTheCompileDbIsResolvedAgainstTheDirectoryThePathsCameFrom(_TmpProject):
    """The COMMON C/C++ layout: compile DB at the root, `.clang-tidy` in a subdir.

    The precondition resolves `paths` against the git ROOT, but every production
    caller hands it paths relative to the CONFIG DIRECTORY — the linter runs FROM
    there (`lint_invocation_target`), so its args are relative to it. With the
    config one level down, `src/app.c` reaches the precondition as `app.c`, which
    resolves to `<root>/app.c`, whose parent is not in the covered set — so the
    argv comes back None, the batch reports `unverified`, and the gate FAILS
    CLOSED on a project whose database covers the file perfectly well.

    Nothing in the diff can fix that: it is the unfixable block the degrade
    doctrine exists to prevent, reintroduced through an inconsistent path base.
    The two legs are tested end to end (a clean file must not block, a dirty one
    must block on the REAL finding) because a half-fix that merely stops blocking
    would hand C/C++ back its false-clean.
    """

    def setUp(self):
        super().setUp()
        # A real repo: staged_lint resolves the root via git, and a tmpdir that
        # happens to sit inside one would resolve to the WRONG root.
        subprocess.run(
            ["git", "init", "-q"], cwd=str(self.d), check=True, capture_output=True
        )
        (self.d / "inc").mkdir()
        (self.d / "src").mkdir()
        (self.d / "inc" / "hdr.h").write_text("#define ANSWER 42\n")
        # The config lives in the SUBDIRECTORY — the whole point.
        (self.d / "src" / ".clang-tidy").write_text(_CLANG_TIDY_CONFIG)
        # The DB is at the ROOT and covers src/ — the layout cmake/bear produce.
        (self.d / "compile_commands.json").write_text(
            json.dumps(
                [
                    {
                        "directory": str(self.d),
                        "command": "cc -Iinc -c src/app.c",
                        "file": str(self.d / "src" / "app.c"),
                    }
                ]
            )
        )

    def _write_app(self, body: str) -> None:
        (self.d / "src" / "app.c").write_text(body)

    _DIRTY = '#include "hdr.h"\nint main(void){ if (ANSWER) return 0; return 1; }\n'
    _CLEAN = (
        '#include "hdr.h"\n'
        "int main(void) {\n"
        "    if (ANSWER) {\n"
        "        return 0;\n"
        "    }\n"
        "    return 1;\n"
        "}\n"
    )

    def test_a_covered_file_under_a_subdir_config_is_not_degraded(self):
        self._write_app(self._DIRTY)

        self.assertTrue(
            linters.is_file_scoped("clang-tidy", str(self.d), ["src/app.c"]),
            "the DB covers src/ — this file is genuinely gatable",
        )

    def test_the_argv_builds_when_the_paths_are_relative_to_the_config_dir(self):
        """What production actually passes: cwd=<root>/src, paths=['app.c']."""
        self._write_app(self._DIRTY)

        self.assertIsNotNone(
            linters.linter_argv(
                "clang-tidy", ["app.c"], root=str(self.d), base=str(self.d / "src")
            ),
            "the DB covers <root>/src/app.c; refusing to invoke is an unfixable block",
        )

    def test_a_clean_file_does_NOT_block_the_commit(self):
        """The fail-closed. Before the fix this raised BlockedError('unverified')."""
        self._write_app(self._CLEAN)

        advisories = staged_lint.staged_lint_gate(["src/app.c"], str(self.d))

        self.assertEqual(advisories, [], "a covered, clean file is neither blocked...")

    def test_a_dirty_file_still_blocks_on_the_REAL_finding(self):
        """...nor waved through. The gate must report clang-tidy's own words."""
        self._write_app(self._DIRTY)

        with self.assertRaises(_common.BlockedError) as ctx:
            staged_lint.staged_lint_gate(["src/app.c"], str(self.d))

        message = str(ctx.exception)
        self.assertIn("readability-braces", message, "the linter's OWN finding")
        self.assertNotIn("file not found", message, "the DB resolved the include")
        self.assertNotIn("cannot be invoked", message, "not a bad read — a real run")

    def test_the_EDIT_time_path_lints_the_file_too(self):
        """The same base mismatch silently disabled edit-time clang-tidy: it built a
        None argv and returned None, which reads back as CLEAN."""
        self._write_app(self._DIRTY)

        output = lint_check.run_linter(
            "clang-tidy",
            "app.c",
            cwd=str(self.d / "src"),
            root=str(self.d),
            config_path=str(self.d / "src" / ".clang-tidy"),
        )

        self.assertIsNotNone(output, "edit-time must not read a real finding as clean")
        self.assertIn("readability-braces", output or "")


if __name__ == "__main__":
    unittest.main()
