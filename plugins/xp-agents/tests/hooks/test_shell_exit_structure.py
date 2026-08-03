#!/usr/bin/env python3
"""`shell_exit_structure.exit_reaches_shell` — does a command's OWN exit
status reach the shell's exit status?

The runner-agnostic half of `test_attribution.exit_status_proves_runner_passed`,
extracted so a caller that knows nothing about test frameworks can ask the same
structural question. `TestNotVacuousWithoutARunner` is the reason the extraction
exists at all: the runner-aware predicate answers True — *vacuously* — for every
command that names no recognized test runner, so reusing it as a guard would
ship a check that looks present and does nothing.

Structure is the whole vocabulary here. A pipe, `;`, a newline, `||`, a
background `&` or a `$(...)` capture discards or captures a command's exit
status, and which of those happened is decidable from the shell string alone —
in a Python repo, a Rust repo, or a repo with no test runner at all.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from shell_exit_structure import exit_reaches_shell
from test_attribution import exit_status_proves_runner_passed


class TestExitReachesShell(unittest.TestCase):
    """The structural predicate, over commands from several ecosystems."""

    def test_a_simple_command_reaches(self) -> None:
        for command in (
            "pytest -n auto",
            "tsc --noEmit",
            "cargo build",
            "make build",
            "go vet ./...",
            "bundle exec rspec",
            "sh -c 'exit 3'",
        ):
            with self.subTest(command=command):
                self.assertTrue(exit_reaches_shell(command))

    def test_and_chains_reach(self) -> None:
        """`&&` is the one operator that carries a failure through."""
        for command in ("cd app && pytest", "npm ci && npm test", "a && b && c"):
            with self.subTest(command=command):
                self.assertTrue(exit_reaches_shell(command))

    def test_a_trailing_operator_discards_nothing(self) -> None:
        """`make test\\n` IS `make test`. Reading the trailing operator as a
        discard is the deadlock direction the runner-aware predicate was
        rewritten to avoid; the extraction must not reintroduce it."""
        for command in ("make test\n", "make test;", "make test ; \n"):
            with self.subTest(command=command):
                self.assertTrue(exit_reaches_shell(command))

    def test_a_pipe_discards(self) -> None:
        """The spike's own method failure: `$?` after a pipe is the LAST
        stage's, so a red run reads as green."""
        for command in (
            "pytest -n auto | tee log",
            "tsc --noEmit | tee log",
            "make build | tee log",
            "cargo build | tee log",
            "go vet ./... | tee log",
        ):
            with self.subTest(command=command):
                self.assertFalse(exit_reaches_shell(command))

    def test_a_sequence_operator_discards(self) -> None:
        for command in (
            "make build; echo done",
            "make build\necho done",
            "make build || true",
        ):
            with self.subTest(command=command):
                self.assertFalse(exit_reaches_shell(command))

    def test_backgrounding_discards(self) -> None:
        """`&` returns before the command has produced an exit status."""
        self.assertFalse(exit_reaches_shell("npm start &"))

    def test_a_capture_discards(self) -> None:
        for command in ("OUT=$(tsc --noEmit)", "echo $(make build)", "echo `make`"):
            with self.subTest(command=command):
                self.assertFalse(exit_reaches_shell(command))

    def test_a_redirect_is_not_backgrounding(self) -> None:
        """`2>&1` and `&>` are redirects, not `&`. Reading them as async would
        refuse the most ordinary declared command there is."""
        for command in ("make build 2>&1", "make build &> log"):
            with self.subTest(command=command):
                self.assertTrue(exit_reaches_shell(command))

    def test_quoted_operators_are_data(self) -> None:
        """`-k "a | b"` is an argument, not a pipeline."""
        self.assertTrue(exit_reaches_shell('pytest -k "a | b"'))
        self.assertTrue(exit_reaches_shell("cargo test -- --skip 'a; b'"))

    def test_a_shell_c_body_is_code_not_data(self) -> None:
        """`sh -c` takes CODE, so a pipe INSIDE the body discards exactly as an
        unwrapped one does — the wrapper must not launder it."""
        self.assertFalse(exit_reaches_shell("sh -c 'tsc --noEmit | tee log'"))
        self.assertFalse(exit_reaches_shell('bash -c "make build; echo done"'))
        self.assertTrue(exit_reaches_shell("sh -c 'tsc --noEmit'"))
        self.assertTrue(exit_reaches_shell('bash -c "cd app && make build"'))

    def test_a_shell_c_wrapper_does_not_launder_an_outer_pipe(self) -> None:
        self.assertFalse(exit_reaches_shell("sh -c 'make build' | tee log"))

    def test_an_empty_command_reaches_vacuously(self) -> None:
        """Nothing ran, so nothing was swallowed. `differential` refuses an
        empty command on its own grounds, not on this predicate's."""
        self.assertTrue(exit_reaches_shell(""))


class TestNotVacuousWithoutARunner(unittest.TestCase):
    """Why this predicate had to be extracted rather than reused.

    `exit_status_proves_runner_passed` is *vacuously* True whenever the command
    names no recognized test-framework runner — there is no runner exit status
    for a pipe to have swallowed, which is the right answer to ITS question and
    the wrong answer to this one. The checkout-VARIANT artifact spike-005
    measured was a typecheck, precisely a command with no test runner in it, so
    reusing it would have shipped a guard that fires on `pytest | tee log` and
    on nothing else a project is likely to declare.
    """

    NON_TEST_PIPELINES = (
        "tsc --noEmit | tee log",
        "make build | tee log",
        "cargo build | tee log",
        "go vet ./... | tee log",
    )

    def test_runner_aware_predicate_clears_these_vacuously(self) -> None:
        """Pins the premise. If this ever goes red the reuse argument changes,
        and the test below should be re-derived rather than patched."""
        for command in self.NON_TEST_PIPELINES:
            with self.subTest(command=command):
                self.assertTrue(exit_status_proves_runner_passed(command))

    def test_structural_predicate_catches_them(self) -> None:
        for command in self.NON_TEST_PIPELINES:
            with self.subTest(command=command):
                self.assertFalse(exit_reaches_shell(command))


if __name__ == "__main__":
    unittest.main()
