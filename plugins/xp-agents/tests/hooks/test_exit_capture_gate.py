#!/usr/bin/env python3
"""Tests for exit_capture_gate.py — refuse a runner whose exit status is lost.

The gate answers one question: if this command runs, will the shell's exit
status be the runner's? When it will not, a passing suite cannot clear an open
test-failure concern, so the agent is told tests are failing while they pass
and burns a whole run chasing it. That happened twelve times across three
sessions before this gate existed.

Structure of the suite mirrors the gate's four inputs: is there a declaration,
does the command invoke it, is the escape marker present, and does the exit
survive. Each gets a class, plus one for the refusal text — a refusal that does
not say what to run instead is a dead end, not a gate.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import exit_capture_gate
from _system_context_fixtures import valid_doc, write_doc
from conftest import _SMMTestCase
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_DECLARED = "pytest -n auto"

# Every shape recorded on the concern this story closes, plus the ones the
# structural walk already knew about. Keyed by what swallowed the status.
_MASKING_SHAPES = {
    "pipe": "pytest -n auto | tail -20",
    "pipe-with-stderr": "pytest -n auto 2>&1 | tee /tmp/suite.log",
    "redirect-then-echo": "pytest -n auto > /tmp/suite.log\necho $?",
    "assignment-capture": "OUT=$(pytest -n auto)",
    "consumed-capture": "echo $(pytest -n auto)",
    "backtick-capture": "echo `pytest -n auto`",
    "background": "pytest -n auto &",
    "semicolon": "pytest -n auto; echo done",
    "or-mask": "pytest -n auto || true",
}

# Shapes that keep the runner's exit status. `&&` short-circuits, so the
# runner's non-zero IS the shell's — refusing these would deadlock the gate
# against the ordinary `cd <dir> && <runner>` every worktree run uses.
_HONEST_SHAPES = {
    "bare": "pytest -n auto",
    "narrowed": "pytest plugins/xp-agents/tests/hooks/test_x.py",
    "leading-cd": "cd plugins && pytest -n auto",
    "trailing-and": "pytest -n auto && echo green",
    "both": "cd plugins && pytest -n auto && echo green",
    "trailing-newline": "pytest -n auto\n",
    "argument-substitution": "pytest -n $(nproc)",
    "argument-substitution-flag": "pytest --rootdir=$(pwd) tests/",
}


class _GateCase(_SMMTestCase):
    """An SMM whose system_context may declare a test command."""

    def declare(self, command: str = _DECLARED) -> None:
        write_doc(
            self.smm_dir,
            valid_doc(stack={"languages": ["Python"], "test_command": command}),
        )

    def block(self, command: str) -> str | None:
        return exit_capture_gate.captured_exit_block(self.smm_dir, command)

    def assert_refused(self, command: str) -> str:
        reason = self.block(command)
        self.assertIsNotNone(reason, msg=f"expected a refusal for: {command!r}")
        assert reason is not None
        return reason

    def assert_allowed(self, command: str) -> None:
        self.assertIsNone(
            self.block(command), msg=f"expected no refusal for: {command!r}"
        )


class TestMaskedExitIsRefused(_GateCase):
    """AC1: the runner runs, but its exit status never reaches the shell."""

    def test_every_masking_shape_is_refused(self):
        self.declare()
        for name, command in _MASKING_SHAPES.items():
            with self.subTest(shape=name):
                self.assert_refused(command)

    def test_a_narrowed_invocation_is_refused_too(self):
        """The declaration supplies the executable, not the whole command —
        so the shapes an agent actually types are covered, not just the CI
        form. This is the case a token-prefix match would have missed."""
        self.declare()
        self.assert_refused("pytest tests/hooks/test_x.py | tail -30")
        self.assert_refused("pytest x.py::TestClass::test_y > out.txt\necho $?")

    def test_a_wrapped_invocation_is_refused(self):
        self.declare()
        self.assert_refused("cd plugins && pytest -n auto | tail -5")


class TestHonestShapesProceed(_GateCase):
    """AC2, and the deadlock this gate must not create.

    A gate that refuses `cd <dir> && <runner>` refuses the shape every
    worktree run takes, and there is then no command left that clears the
    concern.
    """

    def test_every_honest_shape_proceeds(self):
        self.declare()
        for name, command in _HONEST_SHAPES.items():
            with self.subTest(shape=name):
                self.assert_allowed(command)

    def test_a_substitution_that_closes_before_the_runner_proceeds(self):
        self.declare()
        self.assert_allowed("cd $(git rev-parse --show-toplevel) && pytest -n auto")

    def test_an_argument_substitution_running_the_same_executable_proceeds(self):
        """The shape that makes reusing the argument-substitution rewrite
        load-bearing rather than decorative: the substitution computes an
        ARGUMENT, and its head token is the declared executable, so a walk
        that read every `$(...)` as a capture would refuse a command whose
        exit status is perfectly honest."""
        write_doc(
            self.smm_dir,
            valid_doc(stack={"languages": ["Go"], "test_command": "go test ./..."}),
        )
        self.assert_allowed("go test $(go list ./...)")


class TestCommandsThatDoNotRunTheRunner(_GateCase):
    """AC4: a command the gate cannot classify as a runner invocation is not
    this gate's business, however badly it treats its own exit status. The
    post-hoc advisory remains the fallback for those."""

    def test_unrelated_masked_commands_proceed(self):
        self.declare()
        for command in (
            "make build | tail -20",
            "grep -rn pytest plugins/ | head",
            "cat pytest.ini > /tmp/x\necho $?",
            "OUT=$(git status --short)",
            "npm run lint &",
        ):
            with self.subTest(command=command):
                self.assert_allowed(command)


class TestNoDeclarationMeansNoGate(_GateCase):
    """AC: a project that declares nothing gets today's behaviour exactly.

    Not a degradation to tolerate but the correct answer: with no
    declaration there is no way to tell a runner invocation from any other
    command, and refusing on a guess would refuse ordinary work.
    """

    def test_absent_system_context_no_ops(self):
        for command in _MASKING_SHAPES.values():
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_unset_test_command_no_ops(self):
        write_doc(self.smm_dir, valid_doc())
        for command in _MASKING_SHAPES.values():
            with self.subTest(command=command):
                self.assert_allowed(command)

    def test_blank_test_command_no_ops(self):
        self.declare("   ")
        self.assert_allowed("pytest -n auto | tail")

    def test_corrupt_system_context_no_ops_without_raising(self):
        """A PreToolUse hook that raises does not block — it errors, the
        command runs anyway, and the raise repeats on every later Bash call.
        So the unreadable-declaration path must be a no-op, and must be
        reached without an exception escaping."""
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text("{ not json")
        self.assert_allowed("pytest -n auto | tail -20")

    def test_schema_invalid_system_context_no_ops_without_raising(self):
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps({"product": "only this"})
        )
        self.assert_allowed("pytest -n auto | tail -20")

    def test_empty_command_no_ops(self):
        self.declare()
        self.assert_allowed("")


class TestEscapeHatch(_GateCase):
    """A refusal an author cannot override is a refusal that gets routed
    around invisibly. The marker is a plain shell comment — inert to the
    command, greppable in history, and it forces the intent to be stated.
    """

    def test_the_marker_suppresses_an_otherwise_refused_command(self):
        self.declare()
        marker = exit_capture_gate.EXIT_STATUS_NOT_NEEDED_MARKER
        for name, command in _MASKING_SHAPES.items():
            with self.subTest(shape=name):
                self.assert_refused(command)
                self.assert_allowed(f"{command}  {marker}")

    def test_its_absence_does_not_suppress(self):
        """A near-miss must not work, or the marker stops being a statement
        of intent and becomes a spelling exercise."""
        self.declare()
        for near_miss in (
            "# exit status not needed",
            "# exit-status-not-required",
            "# no-exit-status",
        ):
            with self.subTest(near_miss=near_miss):
                self.assert_refused(f"pytest -n auto | tail  {near_miss}")

    def test_the_marker_is_a_shell_comment(self):
        """Inert to the command it rides on — otherwise the escape hatch
        changes what runs, which no escape hatch may do."""
        self.assertTrue(exit_capture_gate.EXIT_STATUS_NOT_NEEDED_MARKER.startswith("#"))


class TestTheRefusalIsActionable(_GateCase):
    """AC1's second half: the reason must name the bare form to run instead.

    The failure this gate exists to prevent is an agent burning a run on a
    phantom. A refusal that does not say what to type next spends the same
    run a different way.
    """

    def test_the_reason_names_the_declared_command(self):
        self.declare()
        reason = self.assert_refused("pytest -n auto | tail -20")
        self.assertIn(_DECLARED, reason)

    def test_the_reason_names_the_escape_marker(self):
        self.declare()
        reason = self.assert_refused("pytest -n auto | tail -20")
        self.assertIn(exit_capture_gate.EXIT_STATUS_NOT_NEEDED_MARKER, reason)

    def test_the_reason_names_the_projects_own_command_not_a_builtin_one(self):
        """The reason is built from the declaration, so a project running
        something the plugin has never heard of is told to run ITS command."""
        write_doc(
            self.smm_dir,
            valid_doc(stack={"languages": ["Elixir"], "test_command": "mix test"}),
        )
        reason = self.assert_refused("mix test | tail -20")
        self.assertIn("mix test", reason)

    def test_the_reason_says_that_an_and_chain_is_still_fine(self):
        """Without this the obvious reading of the refusal is "never compose
        the test command", and the next command tried is a bare re-run that
        drops the `cd` the worktree needs."""
        self.declare()
        reason = self.assert_refused("pytest -n auto | tail -20")
        self.assertIn("&&", reason)


class TestShellWrappersCannotLaunder(_GateCase):
    """`sh -c` is code, not data, so it may not become a way to hide either
    the runner or the operator that swallowed its status."""

    def test_a_pipe_outside_the_wrapper_is_refused(self):
        self.declare()
        self.assert_refused('sh -c "cd plugins && pytest -n auto" | tail -20')

    def test_a_pipe_inside_the_wrapper_is_refused(self):
        self.declare()
        self.assert_refused('bash -c "pytest -n auto | tail -20"')

    def test_an_honest_wrapper_body_proceeds(self):
        self.declare()
        self.assert_allowed('sh -c "cd plugins && pytest -n auto"')

    def test_a_quoted_mention_is_not_a_wrapper(self):
        """`python3 -c` and `git commit -m` quote text they never execute as
        shell code; only a POSIX shell's `-c` body is code."""
        self.declare()
        self.assert_allowed('git commit -m "stop piping pytest | tail"')


# The module may hold no runner vocabulary either — it composes the
# declaration-reading module, and a name here would be the same leak one
# indirection further out.
_RUNNER_LITERALS = (
    "pytest", "unittest", "jest", "vitest", "mocha", "playwright", "deno",
    "turbo", "nx", "bun", "npm", "pnpm", "yarn", "lerna", "cargo", "gradle",
    "maven", "mvn", "rspec", "minitest", "phpunit", "dotnet", "swift",
    "xcodebuild", "rake", "tox", "nose2", "ctest",
)  # fmt: skip


class TestShippedSourceNamesNoRunner(unittest.TestCase):
    """AC3's literal half, applied to the gate as well as to its input."""

    def test_no_runner_name_appears_in_the_shipped_module(self):
        module = Path(exit_capture_gate.__file__)
        source = module.read_text(encoding="utf-8")
        found = sorted(
            name
            for name in _RUNNER_LITERALS
            if re.search(rf"\b{re.escape(name)}\b", source, re.IGNORECASE)
        )
        self.assertEqual(
            found,
            [],
            msg=(
                f"{module.name} names {found} — every refusal this gate makes "
                f"must derive from the project's declaration. A runner name "
                f"here is the table this design routes around, one module out."
            ),
        )


if __name__ == "__main__":
    unittest.main()
