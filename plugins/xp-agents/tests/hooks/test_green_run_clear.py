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
from _commit_helpers import patch_commits
from concerns import TEST_FAILURES_PREFIX
from conftest import _HookTestCase, _make_bash_input, make_event
from event_schema import EVENT_TYPE_CONCERN

_WATERMARK_ID = "test-green-run-clear"


class TestClearRequiresAnObservedRun(_HookTestCase):
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

    def _open_failure(self) -> dict:
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"{TEST_FAILURES_PREFIX}: 3 failed (pytest)",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)
        return concern

    def _run_green(self, command: str, stdout: str) -> bool:
        """Drive the PostToolUse path; return True if the concern got resolved."""
        with patch_commits(files=[], body=""):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=stdout),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return any(e.get("metadata", {}).get("resolves") for e in events)

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


class TestCapturedRunnerDoesNotClear(_HookTestCase):
    """The other half of the disarm: the runner really RAN, but its exit
    status never reached the command's.

    Live evidence: `OUT=$(pytest tests/); echo $?` exited 0 while the pytest
    inside exited 1. `is_test_run` matched, the runner was in executable
    position, and the hook resolved every open test-failure concern and
    announced "All prior test failures resolved" over a red suite.

    `TestClearRequiresAnObservedRun` asks "did a runner run?"; this asks the
    question that one assumed away — "does the 0 belong to it?".
    """

    def _open_failure(self) -> dict:
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"{TEST_FAILURES_PREFIX}: 3 failed (pytest)",
            severity="high",
        )
        _common.append_safe(self.smm_dir, concern)
        return concern

    def _run_green(self, command: str, stdout: str) -> bool:
        with patch_commits(files=[], body=""):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=stdout),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return any(e.get("metadata", {}).get("resolves") for e in events)

    def test_live_evidence_capture_does_not_clear(self):
        """Verbatim: the command that actually disarmed the gate."""
        self._open_failure()
        self.assertFalse(
            self._run_green("OUT=$(pytest tests/); echo $?", "1\n"),
            "a captured runner's exit says nothing about the suite",
        )

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


if __name__ == "__main__":
    unittest.main()
