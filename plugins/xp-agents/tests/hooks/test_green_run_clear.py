#!/usr/bin/env python3
"""Tests for the CLEAR direction of the test-failure gate.

`bash_post_tool`'s success path decides when a green Bash run may resolve open
test-failure concerns. Two independent premises have to hold before it may, and
each was believed and then disproved by live evidence:

  * a runner actually RAN — `is_test_run` matches a runner NAME anywhere, so a
    succeeding `grep -rn pytest src/` cleared a red suite; and
  * the 0 we just saw IS that runner's — `OUT=$(pytest); echo $?` exits 0 with
    a red pytest inside.

Split out of test_bash_failure.py, which covers the opposite (write) direction.
Clearing on a lie DISARMS the gate, so every class here carries anti-deadlock
controls alongside the refusals: refusing too much is the other way to break it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import tdd_check
from _commit_helpers import patch_commits
from concerns import TEST_FAILURES_PREFIX
from conftest import _HookTestCase, _make_bash_input, _MixinBase, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

_WATERMARK_ID = "test-green-run-clear"


class _GreenRunMixin(_MixinBase):
    """The fixture every class here needs: one open test-failure concern, and
    a driver for `bash_post_tool`'s success path."""

    smm_dir: Path

    def _open_failure(self) -> dict:
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"{TEST_FAILURES_PREFIX}: 3 failed (pytest)",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)
        return concern

    def _run(self, command: str, stdout: str) -> str | None:
        """Drive the PostToolUse path; return the nudge/advisory it emits."""
        with patch_commits(files=[], body=""):
            return bash_post_tool.run(
                _make_bash_input(command=command, stdout=stdout),
                smm_dir=self.smm_dir,
            )

    def _events(self) -> list[dict]:
        return _common.read_events_locked(self.smm_dir, _WATERMARK_ID)

    def _run_green(self, command: str, stdout: str) -> bool:
        """True when the run RESOLVED an open test-failure concern."""
        self._run(command, stdout)
        return any(e.get("metadata", {}).get("resolves") for e in self._events())


class TestClearRequiresAnObservedRun(_GreenRunMixin, _HookTestCase):
    """The CLEAR side of the same defect the writer side just fixed.

    `bash_post_tool` reaches its clear branch on any SUCCEEDING command that
    `is_test_run` matches — and `is_test_run` matches a runner name ANYWHERE,
    including as an argument. So a successful `grep -rn pytest plugins/`
    resolved EVERY open test-failure concern: a real red suite silently
    un-gated by grepping for the word. Attributing too little on the write
    side files a false concern; clearing on a run that never happened DISARMS
    the gate, which is the far worse direction.

    The clear is gated on the runner occupying the EXECUTABLE position, NOT on
    the parser having extracted counts — that distinction is what keeps this
    from deadlocking (see test_unparseable_green_run_still_clears).
    """

    def test_grep_for_runner_name_does_not_clear(self):
        """The disarm. `grep` exits 0 when it MATCHES — so grepping for the
        word `pytest` while a suite is red wiped the gate."""
        self._open_failure()
        self.assertFalse(
            self._run_green(
                "grep -rn pytest plugins/",
                "plugins/xp-agents/scripts/bash_failure.py:12:import pytest\n",
            ),
            "a grep that never ran a test must not resolve a test failure",
        )

    def test_cat_of_a_runner_config_does_not_clear(self):
        self._open_failure()
        self.assertFalse(self._run_green("cat pytest.ini", "[pytest]\n"))

    def test_real_green_run_still_clears(self):
        """Anti-deadlock control #1: the ordinary path must keep working."""
        self._open_failure()
        self.assertTrue(self._run_green("python3 -m pytest tests/", "5 passed in 1.2s"))

    def test_unparseable_green_run_still_clears(self):
        """Anti-deadlock control #2, and the reason the clear is gated on the
        EXECUTABLE POSITION rather than on parser_status.

        For a framework whose output this parser cannot read, a failing run
        writes an exit-code concern (bash_failure) and the later passing run is
        equally unparseable. Requiring parsed counts to clear would leave that
        concern open forever — the gate would deadlock. Requiring only that the
        runner actually RAN clears it.
        """
        self._open_failure()
        self.assertTrue(
            self._run_green("mix test", "some output this parser cannot read")
        )

    def test_compound_green_run_still_clears(self):
        """Anti-deadlock control #3: being compound is not, by itself, a reason
        to refuse.

        Every segment of a compound DOES run — that much of the original
        premise held. What did not is the step after it, "so the runner
        passed": only `&&` carries the runner's failure out to the overall exit
        (see TestCapturedRunnerDoesNotClear). Here the runner is last and
        nothing follows it to swallow anything, so exit 0 really is the
        runner's and the clear stands. Refusing on compoundness alone would
        deadlock the gate for anyone who prefixes a `cd`.
        """
        self._open_failure()
        self.assertTrue(self._run_green("cd app && npx jest", "Tests: 5 passed"))

    def test_substitution_closed_before_the_runner_still_clears(self):
        """Anti-deadlock control #4, and why capture is tracked as DEPTH.

        A flat "a `$(` appeared" rule refuses this extremely ordinary
        repo-root shape. The substitution opens and CLOSES before the runner,
        which is left in plain executable position with its exit intact.
        """
        self._open_failure()
        self.assertTrue(
            self._run_green(
                "cd $(git rev-parse --show-toplevel) && pytest", "5 passed in 1.2s"
            )
        )


class TestCapturedRunnerDoesNotClear(_GreenRunMixin, _HookTestCase):
    """The other half of the disarm: the runner really RAN, but its exit
    status never reached the command's.

    Live evidence: `OUT=$(pytest tests/); echo $?` exited 0 while the pytest
    inside exited 1. `is_test_run` matched, the runner was in executable
    position, and the hook resolved every open test-failure concern and
    announced "All prior test failures resolved" over a red suite.

    `TestClearRequiresAnObservedRun` asks "did a runner run?"; this asks the
    question that one assumed away — "does the 0 belong to it?".
    """

    def test_live_evidence_capture_does_not_clear(self):
        """Verbatim: the command that actually disarmed the gate."""
        self._open_failure()
        self.assertFalse(
            self._run_green("OUT=$(pytest tests/); echo $?", "1\n"),
            "a captured runner's exit says nothing about the suite",
        )

    def test_shell_c_wrapper_does_not_launder_a_swallowed_exit(self):
        """The wrapper shape of the same disarm.

        `executed_framework` reads the `sh -c` body and correctly reports a
        runner; the operator scan runs over quote-stripped text where the body
        is gone. So the pipe that swallowed the runner's exit sat after a
        segment the scan thought ran nothing — and the clear went through on
        tee's 0.
        """
        self._open_failure()
        self.assertFalse(self._run_green('sh -c "pytest" | tee out.log', "5 passed"))

    def test_shell_c_wrapper_with_surviving_exit_still_clears(self):
        """Anti-deadlock control for the wrapper: nothing follows the runner,
        so its 0 really is the command's."""
        self._open_failure()
        self.assertTrue(self._run_green('sh -c "pytest tests/"', "5 passed in 1.2s"))

    def test_swallowed_exit_does_not_clear(self):
        """Every operator that drops the runner's failure on the floor.

        One concern for the whole loop: it must survive ALL of them, and a
        clear by any one shape leaves a resolution in the log that the
        remaining subtests then see too — which is the honest reading, since
        the gate is disarmed from that point on either way.
        """
        self._open_failure()
        for command in (
            "pytest ; echo done",
            "pytest || true",
            "pytest | tee out.log",
            "echo $(pytest)",
        ):
            with self.subTest(command=command):
                self.assertFalse(self._run_green(command, "5 passed in 1.2s"))


class TestCapturedRunnerStatusEmission(_GreenRunMixin, _HookTestCase):
    """The SECOND way a green run un-gates a red one: the STATUS event itself.

    Resolving concerns is not the only leg. `tdd_check.find_last_test_signal`
    walks the log backwards and returns "pass" the moment it meets a status
    matching its pass pattern — short-circuiting before it ever reaches the
    open failure concern, with no resolution event anywhere. That append sits
    in the is-a-test-run branch, OUTSIDE the clear branch's guard, so gating
    only the clear leaves a PASS-shaped digest to un-gate the suite anyway.

    `pytest | tee out.log` is the shape that makes this concrete rather than
    hypothetical: the pipe hands tee the runner's output verbatim (so the
    counts really do parse as green) while handing the shell only TEE's exit
    status — the runner may have been red the whole time.
    """

    CAPTURED = "python3 -m pytest tests/ | tee out.log"
    GREEN_OUTPUT = "5 passed in 1.20s"

    def _statuses(self) -> list[dict]:
        return events_of_type(self._events(), EVENT_TYPE_STATUS)

    def test_captured_runner_emits_no_pass_shaped_status(self):
        """The digest must not read as a pass the gate would trust."""
        self._run(self.CAPTURED, self.GREEN_OUTPUT)
        statuses = self._statuses()
        self.assertEqual(len(statuses), 1, "the run is still recorded, just honestly")
        self.assertIsNone(
            tdd_check.TEST_PASS_RE.search(statuses[0]["content"]),
            f"un-gating status content: {statuses[0]['content']!r}",
        )

    def test_captured_runner_does_not_un_gate_tdd_check(self):
        """End to end through the consumer that the shape actually fools."""
        self._open_failure()
        self._run(self.CAPTURED, self.GREEN_OUTPUT)
        self.assertEqual(tdd_check.find_last_test_signal(self._events()), "fail")

    def test_uncaptured_green_run_still_emits_a_pass(self):
        """Anti-deadlock control: the honest green path is untouched, or
        nothing would ever un-gate a red run again."""
        self._open_failure()
        self._run("python3 -m pytest tests/", self.GREEN_OUTPUT)
        statuses = self._statuses()
        self.assertIsNotNone(tdd_check.TEST_PASS_RE.search(statuses[0]["content"]))

    def test_refusal_is_explained_and_names_capture(self):
        """A silent refusal is an armed gate with no way out: the agent sees
        no reason and no hint that a plain re-run clears it. The reason must
        point at the captured exit status, not at being compound — plenty of
        compounds still clear."""
        advisory = self._assert_not_none(self._run(self.CAPTURED, self.GREEN_OUTPUT))
        self.assertIn("exit status", advisory.lower())
        self.assertNotIn("compound", advisory.lower())

    def test_live_evidence_does_not_report_failures_resolved(self):
        """AC #5, verbatim: the command that announced a red suite green.

        `OUT=$(pytest ...)` captures the runner's exit into a string and
        `echo $?` reports the SUBSTITUTION's status, so the shell sees 0 over
        a suite that exited 1.

        The gate assertion carries the weight here. Suppressing the message
        alone would be cosmetic — the disarm is the resolution event it
        announces, and `find_last_test_signal` is what the stop gate reads.
        """
        self._open_failure()
        advisory = self._run("OUT=$(python3 -m pytest tests/); echo $?", "1\n")
        self.assertNotIn("All prior test failures resolved", advisory or "")
        self.assertEqual(tdd_check.find_last_test_signal(self._events()), "fail")


if __name__ == "__main__":
    unittest.main()
