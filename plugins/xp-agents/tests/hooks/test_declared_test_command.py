#!/usr/bin/env python3
"""Tests for declared_test_command.py — the project's DECLARED runner.

Two halves, tested separately because they fail differently: reading the
declaration off disk (absent / blank / corrupt / symlinked) and deciding
whether a shell text invokes it.

THE ANTI-LEAK TEST is `TestUnlistedRunnersBehaveIdentically`. The plugin ships
to projects in every language, and the failure this module exists to route
around is a table of runner names — one already exists in the tree, and
building on it would have made the gate inert for every project whose runner
is not in it. So the decisive proof is not that the well-known runners work:
it is that runners NO table anywhere in this repo has heard of work exactly
the same way, and that the shipped module's source names none of them.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import declared_test_command
from _system_context_fixtures import valid_doc, write_doc
from conftest import _SMMTestCase
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_declared = declared_test_command.declared_test_command
_runs = declared_test_command.runs_declared_test_command


class _DeclarationCase(_SMMTestCase):
    """An SMM whose system_context may declare a test command."""

    def declare(self, command: str, languages: tuple[str, ...] = ("Python",)) -> None:
        write_doc(
            self.smm_dir,
            valid_doc(stack={"languages": list(languages), "test_command": command}),
        )

    def write_raw(self, text: str) -> None:
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(text)


class TestReadingTheDeclaration(_DeclarationCase):
    """Absent, blank and unreadable declarations all mean "we cannot tell"."""

    def test_missing_system_context_is_none(self):
        self.assertIsNone(_declared(self.smm_dir))

    def test_unset_test_command_is_none(self):
        write_doc(self.smm_dir, valid_doc())
        self.assertIsNone(_declared(self.smm_dir))

    def test_empty_test_command_is_none(self):
        self.declare("")
        self.assertIsNone(_declared(self.smm_dir))

    def test_whitespace_only_test_command_is_none(self):
        """The schema type- and length-checks this field but does not require
        it to be non-blank, so `"   "` really can be on disk. Returning it
        would hand a caller a declaration whose head token is the empty
        string, which matches nothing and reads as "declared" anyway."""
        self.declare("   \t ")
        self.assertIsNone(_declared(self.smm_dir))

    def test_declared_command_is_returned_stripped(self):
        self.declare("  ./run-suite.sh --fast  ")
        self.assertEqual(_declared(self.smm_dir), "./run-suite.sh --fast")

    def test_corrupt_system_context_returns_none_without_raising(self):
        """A PreToolUse hook that exits non-2 does not block, so a raise here
        would let the command run AND poison every later Bash call in the
        session. With the declaration unreadable we cannot tell whether a
        command invokes the runner at all, so no-op is the only coherent
        answer."""
        self.write_raw("{ not json at all")
        self.assertIsNone(_declared(self.smm_dir))

    def test_schema_invalid_system_context_returns_none_without_raising(self):
        self.write_raw(json.dumps({"product": "only this field"}))
        self.assertIsNone(_declared(self.smm_dir))

    def test_symlinked_system_context_returns_none_without_raising(self):
        """The loader raises OSError, not ValueError, on a symlink — a
        separate except leg, so it gets its own test."""
        target = self.smm_dir / "elsewhere.json"
        target.write_text(json.dumps(valid_doc()))
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).symlink_to(target)
        self.assertIsNone(_declared(self.smm_dir))


class TestHeadTokenMatching(unittest.TestCase):
    """The declaration supplies the head token; everything else is structure.

    Head token, NOT token prefix. The everyday invocations this project's own
    CLAUDE.md documents carry none of the declared flags, so a prefix match
    would ship a gate that never fires.
    """

    DECLARED = "pytest -n auto"

    def test_the_declared_command_itself_matches(self):
        self.assertTrue(_runs(self.DECLARED, self.DECLARED))

    def test_invocations_without_the_declared_flags_match(self):
        for text in (
            "pytest tests/x.py",
            "pytest x.py::TestClass::test_y",
            "pytest --collect-only -q",
            "pytest -k 'not slow' tests/",
        ):
            with self.subTest(text=text):
                self.assertTrue(_runs(text, self.DECLARED))

    def test_commands_that_only_mention_the_runner_do_not_match(self):
        """A head-token test is what keeps a name used as DATA out of the
        gate — the segment's executable is the grep, not the runner."""
        for text in (
            "grep -rn pytest plugins/",
            "cat pytest.ini",
            "echo 'run pytest bare'",
            "git commit -m 'fix pytest flake'",
        ):
            with self.subTest(text=text):
                self.assertFalse(_runs(text, self.DECLARED))

    def test_wrapper_prefixes_are_peeled(self):
        for text in (
            "env FOO=1 pytest tests/",
            "time pytest tests/",
            "nice -n 10 pytest tests/",
            "/usr/local/bin/pytest tests/",
        ):
            with self.subTest(text=text):
                self.assertTrue(_runs(text, self.DECLARED))

    def test_a_blank_declaration_matches_nothing(self):
        """Defence in depth: `declared_test_command` already refuses to return
        one, but the predicate is public and story-012 composes it elsewhere."""
        self.assertFalse(_runs("pytest tests/", ""))
        self.assertFalse(_runs("pytest tests/", "   "))

    def test_empty_text_matches_nothing(self):
        self.assertFalse(_runs("", self.DECLARED))

    def test_non_test_work_by_the_same_executable_also_matches(self):
        """The accepted cost of head-token matching, pinned so it is a
        decision rather than a surprise.

        A declaration whose executable also does non-test work matches that
        work too. Narrowing it would mean reading the declaration's SUBCOMMAND
        — teaching this module what a subcommand is, which is the first
        sentence of the vocabulary the design exists to avoid. A consumer that
        refuses on a match must therefore carry an escape hatch; the gate that
        consumes this does.
        """
        self.assertTrue(_runs("zig build lib", "zig build test"))
        self.assertTrue(_runs("mix deps.get", "mix test"))


class TestCompoundTextIsSplit(unittest.TestCase):
    """`runs_target` is text-shaped, not segment-shaped.

    `shell_exit_structure.outer_exit_reaches_shell` calls its predicate BOTH
    with an already-split outer segment AND with a whole `sh -c` body, which
    may itself be compound. A head-token test applied to an undivided compound
    body answers for the `cd`, so the wrapper would launder the very pipe the
    gate exists to catch.
    """

    DECLARED = "pytest -n auto"

    def test_a_compound_body_whose_later_segment_runs_the_runner_matches(self):
        for text in (
            "cd plugins && pytest -n auto",
            "cd plugins; pytest tests/",
            "make build && pytest tests/",
            "echo starting\npytest tests/",
        ):
            with self.subTest(text=text):
                self.assertTrue(_runs(text, self.DECLARED))

    def test_a_compound_body_that_never_runs_the_runner_does_not_match(self):
        self.assertFalse(_runs("cd plugins && make build", self.DECLARED))


# ---------------------------------------------------------------------------
# The anti-leak proof
# ---------------------------------------------------------------------------

# Runners chosen precisely because NO table in this repo knows them. If the
# implementation ever regains a table, these are what go dark first — which is
# the whole point of asserting on them rather than on the familiar names.
_UNLISTED: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "mix test",
        ("mix test", "mix test test/foo_test.exs", "cd app && mix test --trace"),
        ("grep -rn 'mix test' docs/", "cat mix.exs"),
    ),
    (
        "zig build test",
        ("zig build test", "zig build test --summary all"),
        ("cat build.zig", "echo 'zig build test'"),
    ),
    (
        "dune runtest",
        ("dune runtest", "dune runtest --force lib/"),
        ("opam install .", "ls dune-project"),
    ),
    (
        "./run-suite.sh --fast",
        ("./run-suite.sh", "run-suite.sh -v", "bin/run-suite.sh --slow"),
        ("cat run-suite.sh", "chmod +x run-suite.sh"),
    ),
    (
        "busted --coverage",
        ("busted", "busted spec/thing_spec.lua"),
        ("luarocks install busted",),
    ),
)


class TestUnlistedRunnersBehaveIdentically(unittest.TestCase):
    """AC3, and the defence against re-leaking the project-agnostic guardrail.

    Every runner below is one the plugin has never heard of. If they all
    behave the same as the familiar ones, the knowledge is coming from the
    declaration and nowhere else.
    """

    def test_declared_invocations_match(self):
        for declared, matching, _ in _UNLISTED:
            for text in matching:
                with self.subTest(declared=declared, text=text):
                    self.assertTrue(_runs(text, declared))

    def test_unrelated_commands_do_not_match(self):
        for declared, _, other in _UNLISTED:
            for text in other:
                with self.subTest(declared=declared, text=text):
                    self.assertFalse(_runs(text, declared))

    def test_two_declarations_never_match_each_others_invocations(self):
        """The strongest form: the answer depends ONLY on the declaration.
        If any shared knowledge leaked back in, one project's declaration
        would start recognising another project's runner."""
        for declared, matching, _ in _UNLISTED:
            for other_declared, _, _ in _UNLISTED:
                if other_declared == declared:
                    continue
                for text in matching:
                    with self.subTest(declared=other_declared, text=text):
                        self.assertFalse(_runs(text, other_declared))


class TestTheFamiliarRunnersAreNotSpecialCased(unittest.TestCase):
    """The three the story names, held to the same rule as the unlisted ones."""

    CASES = (
        ("cargo test", "cargo test --lib"),
        ("go test ./...", "go test ./pkg/thing"),
        ("npx jest", "npx jest src/thing.test.ts"),
    )

    def test_declared_invocations_match(self):
        for declared, text in self.CASES:
            with self.subTest(declared=declared):
                self.assertTrue(_runs(text, declared))
                self.assertTrue(_runs(declared, declared))

    def test_head_token_comes_from_the_declaration(self):
        """`npx jest` declares `npx`, not `jest` — because the declaration is
        read as shell structure, not looked up. A table would have said
        `jest`; nothing here can."""
        self.assertTrue(_runs("npx vitest run", "npx jest"))
        self.assertFalse(_runs("jest src/", "npx jest"))


# Names any runner table in this tree would contain. The shipped module must
# name none of them — not in a rule, not in an example, not in prose. An
# example is how the next author learns what the rule is allowed to know.
_RUNNER_LITERALS = (
    "pytest", "unittest", "jest", "vitest", "mocha", "playwright", "deno",
    "turbo", "nx", "bun", "npm", "pnpm", "yarn", "lerna", "cargo", "gradle",
    "maven", "mvn", "rspec", "minitest", "phpunit", "dotnet", "swift",
    "xcodebuild", "rake", "tox", "nose2", "ctest",
)  # fmt: skip


class TestShippedSourceNamesNoRunner(unittest.TestCase):
    """AC3's literal half: no rule keys on a runner name.

    A source scan rather than a behavioural one, because the behavioural
    tests above can only prove that today's inputs are handled — they cannot
    prove that tomorrow's special case is absent.
    """

    MODULE = Path(declared_test_command.__file__)

    def test_no_runner_name_appears_in_the_shipped_module(self):
        source = self.MODULE.read_text(encoding="utf-8")
        found = sorted(
            name
            for name in _RUNNER_LITERALS
            if re.search(rf"\b{re.escape(name)}\b", source, re.IGNORECASE)
        )
        self.assertEqual(
            found,
            [],
            msg=(
                f"{self.MODULE.name} names {found} — the declared command is "
                f"the only runner knowledge this module may hold. The plugin "
                f"ships to projects in every language; a runner name here is "
                f"the start of the table this design exists to route around."
            ),
        )


if __name__ == "__main__":
    unittest.main()
