#!/usr/bin/env python3
"""`exit_status_proves_runner_passed` — did the runner's exit status survive?

Split from `test_test_attribution.py` (501 lines). Attribution asks WHO to blame
for a non-zero exit; this predicate asks a prior question: whether a zero exit
means anything at all. A runner inside `$(...)`, behind a pipe, or backgrounded
has its status captured or discarded, so a green result proves nothing — and the
test-failure gate reads that result.

It is a structural judgement about shell text, not a per-language one: quoting
makes an operator data rather than structure, a `sh -c` body is judged as code,
and an operator with nothing after it discarded nothing. Those cases group here
because each is a way the same predicate can be fooled.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from test_attribution import exit_status_proves_runner_passed

# The live shape of a PostToolUseFailure `error` payload: an "Exit code N"
# line followed by the command's stderr.
BARE_EXIT = "Exit code 1"


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


if __name__ == "__main__":
    unittest.main()
