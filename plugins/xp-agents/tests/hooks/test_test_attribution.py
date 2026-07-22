#!/usr/bin/env python3
"""Tests for test_attribution.py — who do we blame for a non-zero Bash exit?

The gate's teeth depend on this module: attributing too little disarms it for
real failures, attributing too much files "tests are failing" for runs that
never happened. Both directions are pinned here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from test_attribution import (
    attribute_failure,
    exit_status_proves_runner_passed,
    is_compound,
    parsed_failed_count,
    runs_test_binary,
)
from test_parsing import is_test_run

# The live shape of a PostToolUseFailure `error` payload: an "Exit code N"
# line followed by the command's stderr.
BARE_EXIT = "Exit code 1"
# jest/vitest write their summary to STDERR, so a compound JS test failure
# really does carry parseable counts in `error`. This payload is what keeps
# the corroboration branch honest — it is not a hypothetical.
JEST_STDERR = "Exit code 1\nTests:  2 failed, 3 passed, 5 total"
# ...and `error` is not stderr-only: a runner that summarises on STDOUT
# corroborates the same way. Both payloads below are the live shape — the
# recorded false-positive events for this bug contain a linter's stdout
# diagnostics verbatim after the "Exit code N" line.
PYTEST_STDOUT = "Exit code 1\n2 failed, 3 passed in 1.20s"
RUFF_STDOUT = (
    "Exit code 1\nI001 [*] Import block is un-sorted or un-formatted\n"
    "  --> tests/hooks/test_work_selection_decide.py:26:1"
)


class TestIsCompound(unittest.TestCase):
    def test_shell_operators_are_compound(self):
        for command in (
            "cd pkg && pytest",
            "pytest || echo fail",
            "cd pkg; pytest",
            "pytest | tail -5",
            "cd pkg\npytest",
            "pytest $(ls tests)",
            "pytest `ls tests`",
        ):
            with self.subTest(command=command):
                self.assertTrue(is_compound(command))

    def test_plain_command_not_compound(self):
        self.assertFalse(is_compound("python3 -m pytest tests/ -x"))

    def test_quoted_operator_not_compound(self):
        """An operator inside a quoted argument is data, not a segment break."""
        self.assertFalse(is_compound('pytest -k "a && b"'))
        self.assertFalse(is_compound("pytest -k 'a | b'"))


class TestRunsTestBinary(unittest.TestCase):
    def test_runner_as_argument_is_not_a_run(self):
        for command in (
            "grep -rn pytest plugins/",
            "rg pytest",
            "git grep -n pytest",
            "cat pytest.log",
            "env CI=1 grep pytest src/",
            # Head token must survive shell punctuation and wrapper FLAGS —
            # both are ways for an argument-consuming head to slip past the
            # refusal list and re-open the very false positive this fixes.
            "(grep -rn pytest plugins/)",
            "sudo -u ci grep pytest src/",
            "env -u PYTHONPATH grep pytest src/",
            # BOOLEAN wrapper flags. The peel used to consume the next token
            # unconditionally as "the flag's value", which ate the `grep` and
            # left `pytest` as the head — so a grep that merely found nothing
            # (exit 1) was reported as a failing test run, the exact false
            # attribution this module exists to eliminate. A flag consumes a
            # value only when its wrapper says it takes one.
            "time -p grep pytest plugins/",
            "sudo -n grep pytest src/",
            "env -i grep pytest src/",
            "nice -n 10 grep pytest src/",  # value-taking, still peeled correctly
            "xargs -0 grep pytest",
            # `--opt=value` carries its own value; it must not reach forward.
            "env --unset=PYTHONPATH grep pytest src/",
        ):
            with self.subTest(command=command):
                framework = is_test_run(command)
                self.assertIsNotNone(framework, "fixture must look test-shaped")
                self.assertFalse(runs_test_binary(command, str(framework)))

    def test_runner_in_executable_position_is_a_run(self):
        for command in (
            "pytest tests/",
            "python3 -m pytest tests/ -x",
            "npx jest --ci",
            "go test ./...",
            "cd app && npx jest",
            "(cd app && pytest)",
            "sudo -u ci pytest tests/",
            # Wrapper option zones must be peeled, not mistaken for the head.
            # `env -u <VAR>` is this repo's own lefthook shape; `env -i` has no
            # value, so peeling over-consumes — and must still attribute.
            "env -u GIT_DIR -u SMM_DIR pytest -n auto",
            "env -i pytest",
            # The control for the boolean-flag fix: not consuming a boolean
            # flag's "value" must not stop attributing a REAL run behind one.
            "time -p pytest tests/",
            "sudo -n pytest tests/",
            "nice -n 10 pytest tests/",
        ):
            with self.subTest(command=command):
                framework = is_test_run(command)
                self.assertTrue(runs_test_binary(command, str(framework)))


class TestShellCBodies(unittest.TestCase):
    """A POSIX shell's `-c` argument is CODE, not data — quote-stripping it
    away would silently stop attributing every `sh -c "<runner>"` failure,
    which is a disarm (the worse direction)."""

    def test_shell_c_body_is_attributed(self):
        self.assertEqual(
            attribute_failure('bash -c "pytest tests/"', BARE_EXIT), "pytest"
        )
        self.assertEqual(attribute_failure("sh -c 'npm test'", BARE_EXIT), "jest")
        self.assertEqual(attribute_failure('zsh -lc "go test ./..."', BARE_EXIT), "go")

    def test_shell_c_body_still_honours_the_refusal_list(self):
        """Widening into the body must not widen past the argument check."""
        self.assertIsNone(
            attribute_failure('bash -c "grep -rn pytest src/"', BARE_EXIT)
        )

    def test_compound_inside_shell_c_body_needs_corroboration(self):
        """`bash -c "cd app && pytest"` can short-circuit at the cd exactly as
        the unwrapped form does — the wrapper must not launder the ambiguity."""
        command = 'bash -c "cd app && npx jest"'
        self.assertIsNone(attribute_failure(command, BARE_EXIT))
        self.assertEqual(attribute_failure(command, JEST_STDERR), "jest")

    def test_quoted_shell_c_is_not_an_execution(self):
        """A shell invocation quoted INSIDE another command is data, not code."""
        self.assertIsNone(attribute_failure("echo \"sh -c 'pytest'\"", BARE_EXIT))

    def test_non_shell_c_body_is_not_executed_code(self):
        """`-c` on a non-shell may merely MENTION a runner."""
        self.assertIsNone(attribute_failure('python3 -c "import pytest"', BARE_EXIT))


class TestAttributeFailure(unittest.TestCase):
    def test_non_test_command_not_attributed(self):
        self.assertIsNone(attribute_failure("ls -la", BARE_EXIT))

    def test_grep_for_pytest_not_attributed(self):
        """The non-compound door: grep/rg/git-grep exit 1 on no-match.

        Grepping for the word `pytest` while investigating this very bug
        reproduces the bug a compound-only rule would leave open.
        """
        for command in (
            "grep -rn pytest plugins/",
            "rg pytest",
            "git grep -n pytest",
            "(grep -rn pytest plugins/)",
            "sudo -u ci grep pytest src/",
        ):
            with self.subTest(command=command):
                self.assertIsNone(attribute_failure(command, BARE_EXIT))

    def test_framework_comes_from_the_segment_that_ran(self):
        """Anti-disarm: a runner named as DATA must not mask one that really ran.

        `is_test_run` reads the whole command and returns the highest-precedence
        name it sees — "pytest", from the filename. But the segment that
        EXECUTES is `npm test`, and that is the run whose failure we must record.
        """
        self.assertEqual(
            attribute_failure("cat pytest.ini && npm test", JEST_STDERR), "jest"
        )

    def test_compound_validator_failure_not_attributed(self):
        """The original repro: short-circuit at the validator, pytest never ran."""
        command = (
            "python3 plan_cli.py validate --plan plan.json "
            "&& python3 -m pytest plugins/xp-agents/tests"
        )
        error = "Exit code 1\nERROR: design_details 517/500 OVER budget"
        self.assertIsNone(attribute_failure(command, error))

    def test_failing_cd_prefix_not_attributed(self):
        """3 of the 5 live false positives were a failing `cd`, not a test run."""
        command = "cd plugins/xp-agents && pytest tests/"
        error = "Exit code 1\ncd: no such file or directory: plugins/xp-agents"
        self.assertIsNone(attribute_failure(command, error))

    def test_pipe_not_attributed(self):
        """A pipe's exit status belongs to the last segment, not the runner."""
        self.assertIsNone(attribute_failure("pytest tests/ | tail -5", BARE_EXIT))

    def test_bare_pytest_still_attributed(self):
        """Anti-disarm: a single failing runner is still the runner's fault."""
        self.assertEqual(attribute_failure("pytest tests/", BARE_EXIT), "pytest")
        self.assertEqual(
            attribute_failure('python3 -m pytest -k "a and b"', BARE_EXIT), "pytest"
        )

    def test_quoted_operator_still_attributed(self):
        """A quoted `&&` must not be mistaken for a short-circuit."""
        self.assertEqual(attribute_failure('pytest -k "a && b"', BARE_EXIT), "pytest")

    def test_bare_jest_go_still_attributed(self):
        self.assertEqual(attribute_failure("npx jest --ci", BARE_EXIT), "jest")
        self.assertEqual(attribute_failure("go test ./...", BARE_EXIT), "go")

    def test_compound_with_parseable_failure_attributed(self):
        """E2: the common JS monorepo shape. cd succeeds, jest really fails,
        and its counts are in stderr — so the ambiguity is resolved by
        evidence and the concern still gets written."""
        self.assertEqual(attribute_failure("cd app && npx jest", JEST_STDERR), "jest")

    def test_compound_corroboration_is_not_stream_specific(self):
        """The corroboration branch must not be a JS-only affordance.

        `error` carries the failed command's OUTPUT, not just its stderr — the
        live payloads this bug was diagnosed from contain a linter's stdout
        diagnostics verbatim. So a compound failure of a runner that summarises
        on STDOUT corroborates exactly like one that summarises on stderr, and
        the gate keeps its teeth in every language.
        """
        self.assertEqual(
            attribute_failure("ruff check . && pytest tests/", PYTEST_STDOUT), "pytest"
        )
        # ...while the same shape short-circuiting AT the linter carries the
        # linter's output, corroborates nothing, and is not blamed on pytest.
        self.assertIsNone(
            attribute_failure("ruff check . && pytest tests/", RUFF_STDOUT)
        )

    def test_every_framework_still_attributed(self):
        """Anti-drift control. Every framework is_test_run can name must remain
        attributable from its canonical bare invocation — a new framework that
        this module refuses to attribute is a SILENT DISARM of the gate.
        """
        canonical = (
            "pytest",
            "python3 -m unittest discover",
            "npx jest",
            "npx vitest run",
            "npx mocha",
            "node --test",
            "deno test",
            "npx playwright test",
            "turbo run test",
            "nx test my-pkg",
            "bun test",
            "npm test",
            "go test ./...",
            "cargo test",
            "mvn test",
            "./gradlew test",
            "bundle exec rspec",
            "rake test",
            "phpunit",
            "dotnet test",
            "flutter test",
            "mix test",
            "ctest",
            "swift test",
            "xcodebuild test -scheme App",
        )
        for command in canonical:
            with self.subTest(command=command):
                framework = is_test_run(command)
                self.assertIsNotNone(framework, "fixture must be a known runner")
                self.assertEqual(attribute_failure(command, BARE_EXIT), framework)


class TestTrailingOperatorDiscardsNothing(unittest.TestCase):
    """An operator with NOTHING after it swallowed no exit status.

    `pytest tests/\\n` is `pytest tests/`. The split yields an empty final
    segment and a `\\n` operator, and reading that operator as "the exit was
    discarded" refused an ordinary green run: a multi-line Bash block ends in a
    newline, so the gate stopped clearing over a GREEN suite and the TDD stop
    gate kept blocking the agent -- with re-running in the same shape unable to
    fix it. Over-refusal is the deadlock direction this predicate was written to
    avoid, arriving through the shape nobody tested.
    """

    def test_trailing_newline_still_proves(self):
        self.assertTrue(exit_status_proves_runner_passed("pytest tests/"))
        self.assertTrue(exit_status_proves_runner_passed("pytest tests/\n"))
        self.assertTrue(exit_status_proves_runner_passed("npm test\n"))

    def test_trailing_semicolon_still_proves(self):
        self.assertTrue(exit_status_proves_runner_passed("pytest tests/;"))
        self.assertTrue(exit_status_proves_runner_passed("pytest tests/ ; \n"))

    def test_operator_with_a_real_command_after_it_still_refuses(self):
        """The discarding cases must NOT be loosened: what makes a trailing
        operator harmless is the absence of anything after it, not the operator."""
        self.assertFalse(exit_status_proves_runner_passed("pytest tests/\necho hi"))
        self.assertFalse(exit_status_proves_runner_passed("pytest tests/; echo hi"))
        self.assertFalse(exit_status_proves_runner_passed("pytest tests/ | tee log"))


class TestExitStatusProvesRunnerPassed(unittest.TestCase):
    """The CLEAR direction: when does an overall exit 0 actually prove it?

    The premise this predicate replaces — "exit 0 means every segment of a
    compound ran, so no corroboration is needed" — is false for `;`, `|` and
    `||`, and for a runner whose status is CAPTURED. The live evidence:
    `OUT=$(pytest tests/); echo $?` exited 0 while the pytest inside exited 1,
    and the hook announced every prior test failure resolved over a red suite.

    The rule: exit 0 proves the runner passed iff every operator between the
    runner and the end of the command propagates failure. Both directions
    matter — over-refusing DEADLOCKS the gate (the `is_compound` shape, which
    never clears again for anyone who prefixes a `cd`), and under-refusing
    disarms it.
    """

    def test_uncaptured_runner_still_proves_it(self):
        """Anti-deadlock pins. Every one of these must keep clearing, and each
        is a compound the naive `is_compound` refusal would have deadlocked."""
        for command in (
            "pytest",
            "python3 -m pytest tests/ -x",
            "cd app && pytest",
            "pytest && echo ok",
            "cd app && npx jest",
            # A substitution that OPENS AND CLOSES before the runner leaves the
            # runner in plain executable position — a flat "a `$(` appeared"
            # scan deadlocks this very common repo-root shape.
            "cd $(git rev-parse --show-toplevel) && pytest",
            "cd `git rev-parse --show-toplevel` && pytest",
            # ...and a substitution AFTER the runner cannot swallow an exit
            # that has already propagated through `&&`.
            "pytest && echo $(date)",
            # Arguments produced by a substitution are still just arguments.
            "pytest $(ls tests)",
        ):
            with self.subTest(command=command):
                self.assertTrue(exit_status_proves_runner_passed(command))

    def test_captured_runner_does_not_prove_it(self):
        """The live-evidence shape and its siblings: the runner's exit status
        never reaches the overall exit."""
        for command in (
            # Verbatim live evidence — assignment capture, then `echo $?`
            # reports the substitution's status as the command's.
            "OUT=$(pytest tests/); echo $?",
            # Pure capture: no operator FOLLOWS the runner, so an
            # operator-only rule reads this as safe. It is not.
            "echo $(pytest)",
            "echo `pytest`",
            "RESULT=$(npx jest --ci)",
        ):
            with self.subTest(command=command):
                self.assertFalse(exit_status_proves_runner_passed(command))

    def test_discarded_exit_does_not_prove_it(self):
        """Operators that do not propagate the runner's failure."""
        for command in (
            "pytest ; echo done",
            "pytest || true",
            "pytest | tee out.log",
            "pytest -n auto | tail -20",
            "pytest\necho done",
        ):
            with self.subTest(command=command):
                self.assertFalse(exit_status_proves_runner_passed(command))

    def test_quoted_operator_is_data_not_structure(self):
        """`pytest -k "a; b"` is ONE command — the `;` is a selector, not a
        segment break — so it must still clear."""
        self.assertTrue(exit_status_proves_runner_passed('pytest -k "a; b"'))
        self.assertTrue(exit_status_proves_runner_passed("pytest -k 'a | b'"))

    def test_shell_c_body_is_judged_as_code(self):
        """A `sh -c` body is code, so its operators count. The wrapper must not
        launder a discarded exit — nor refuse a clean one."""
        self.assertFalse(exit_status_proves_runner_passed('sh -c "pytest ; echo hi"'))
        self.assertFalse(exit_status_proves_runner_passed('bash -c "pytest | tail -5"'))
        self.assertTrue(exit_status_proves_runner_passed('sh -c "pytest"'))
        self.assertTrue(exit_status_proves_runner_passed('bash -c "cd app && pytest"'))

    def test_operator_after_a_shell_c_wrapper_still_swallows(self):
        """The wrapper does not launder a discarded exit in the OTHER
        direction either.

        `strip_quoted` deletes the body, so the outer scan sees a bare
        `sh -c ` that names no framework — and an operator-position rule that
        never saw a runner out here has nothing to refuse. The runner really
        ran (`executed_framework` reads the body and says so), so this is the
        clear branch's exact shape: exit status belongs to `tee`, the suite
        may be red, and the gate would have cleared.
        """
        for command in (
            'sh -c "pytest" | tee out.log',
            'sh -c "pytest"; echo done',
            'bash -c "pytest" || true',
            'sh -c "pytest" && echo ok | tee log',
        ):
            with self.subTest(command=command):
                self.assertFalse(exit_status_proves_runner_passed(command))

    def test_backgrounded_runner_does_not_prove_it(self):
        """`&` is the operator that discards the exit hardest: the shell does
        not wait at all, so the 0 arrives before a single test has run.

        It is absent from the segment vocabulary on purpose — `2>&1` and `&>`
        put an `&` in commands that are not compound at all, and teaching the
        shared alternation about it would change `is_compound` (and with it the
        write direction's evidence rule) for every redirect. The async form is
        recognized here instead, where the only consequence is refusing to
        clear.
        """
        for command in ("pytest tests/ &", "npm test &", "pytest > out.txt 2>&1 &"):
            with self.subTest(command=command):
                self.assertFalse(exit_status_proves_runner_passed(command))

    def test_redirect_ampersand_is_not_backgrounding(self):
        """Anti-deadlock control: `2>&1` and `&>` are redirects. Refusing on a
        bare `&` scan would stop clearing for the most ordinary shape there
        is."""
        for command in (
            "pytest tests/ 2>&1",
            "pytest &> out.txt",
            "cd app && pytest 2>&1",
        ):
            with self.subTest(command=command):
                self.assertTrue(exit_status_proves_runner_passed(command))

    def test_shell_c_wrapper_anti_deadlock(self):
        """...and the controls: a wrapper whose exit DOES survive still
        clears, and a wrapper running no runner never arms the rule."""
        for command in (
            'sh -c "pytest"',
            'cd app && sh -c "pytest"',
            'sh -c "pytest" && echo ok',
            # No runner inside, so the `;` has no runner exit to swallow —
            # the pytest that follows is the one whose status we see.
            'sh -c "echo hi" ; pytest',
        ):
            with self.subTest(command=command):
                self.assertTrue(exit_status_proves_runner_passed(command))

    def test_commands_that_run_no_runner_are_vacuously_true(self):
        """There is no runner whose exit could have been swallowed, so this
        predicate has nothing to refuse — the executable-position check in
        `executed_framework` is what keeps `grep -rn pytest` from clearing."""
        for command in (
            "ls -la",
            "grep -rn pytest plugins/",
            "cat pytest.ini | head -5",
            "echo $(cat pytest.ini)",
        ):
            with self.subTest(command=command):
                self.assertTrue(exit_status_proves_runner_passed(command))

    def test_first_runner_of_several_must_also_propagate(self):
        """`executed_framework` names the FIRST runner and the clear resolves
        EVERY open test concern, so one swallowed exit is enough to refuse."""
        self.assertFalse(
            exit_status_proves_runner_passed("pytest tests/a; pytest tests/b")
        )

    def test_predicate_is_structural_not_per_language(self):
        """Identical shell shape, every language: the verdict is the shape's."""
        for runner in ("pytest", "npx jest", "go test ./...", "cargo test", "mix test"):
            with self.subTest(runner=runner):
                self.assertTrue(exit_status_proves_runner_passed(f"cd app && {runner}"))
                self.assertFalse(exit_status_proves_runner_passed(f"OUT=$({runner})"))


class TestParsedFailedCount(unittest.TestCase):
    def test_returns_count_when_payload_parses(self):
        self.assertEqual(parsed_failed_count(JEST_STDERR, "jest"), 2)

    def test_none_when_payload_has_no_counts(self):
        self.assertIsNone(parsed_failed_count(BARE_EXIT, "pytest"))

    def test_none_when_parsed_but_green(self):
        """A parsed-but-zero-failure payload is not evidence of a test failure."""
        self.assertIsNone(
            parsed_failed_count("Exit code 1\n5 passed", "pytest"),
        )


if __name__ == "__main__":
    unittest.main()
