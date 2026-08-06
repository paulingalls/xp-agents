#!/usr/bin/env python3
"""No summary line, no recorded result — pinned at the hooks.

Framework detection reads the COMMAND (`is_test_run`), so output from anything
that merely MENTIONS a runner is routed into that runner's parser arm. With no
summary line to anchor on, the arm used to scan the whole response and read a
count out of arbitrary text. Measured live: a probe whose output carried only
a label containing a bare `3 failed` was recorded as a real
zero-passed/three-failed jest run and filed the high-severity concern that
arms the Stop gate, over a fully green suite.

Two hooks share that parser and must answer the same text differently, so both
are pinned here together:

  * `bash_post_tool` RECORDS a result, and must never invent one.
  * `bash_failure` ATTRIBUTES an already-observed non-zero exit. The failure is
    evidence the parse did not produce; it is only deciding whom to blame, so
    it keeps the permissive scan and a real failing `cd app && <runner>` still
    files its concern.

A new file rather than test_bash.py, which sits at its recorded size ceiling.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import bash_post_tool
from conftest import _HookTestCase, _make_bash_failure_input, _make_bash_input
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_STATUS,
    STATUS_ACTION_TEST_RUN_COMPLETE,
)
from test_parsing import PARSER_STATUS_FAILED, PARSER_STATUS_PARSED

_WATERMARK_ID = "test-bash-no-result"

# The live shape behind status 46cac0c5a2c9: a command that names a runner as
# an ARGUMENT, and output whose only count sits in a label.
_LABEL_WITH_A_COUNT = "probe: arm {arm}, fixture 'must report 3 failed rows'\ndone\n"


class _BashHookTestCase(_HookTestCase):
    def _events(self):
        return _common.read_events_locked(self.smm_dir, _WATERMARK_ID)

    def _test_run_status(self, events) -> dict:
        """The one test_run_complete status. Filtered by action rather than
        taken as the only status: a green run can also append a resolution."""
        runs = [
            s
            for s in events_of_type(events, EVENT_TYPE_STATUS)
            if (s.get("metadata") or {}).get("action")
            == STATUS_ACTION_TEST_RUN_COMPLETE
        ]
        self.assertEqual(len(runs), 1, f"expected 1 test-run status, got {len(runs)}")
        return runs[0]


class TestARunnerMentionedButNotRun(_BashHookTestCase):
    """AC1/AC3 — the recording hook records nothing it cannot read."""

    def _run(self, command: str, stdout: str):
        bash_post_tool.run(
            _make_bash_input(command=command, stdout=stdout),
            smm_dir=self.smm_dir,
        )
        return self._events()

    def _assert_no_result(self, events):
        metadata = self._test_run_status(events).get("metadata") or {}
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_FAILED)
        self.assertNotIn("test_passed", metadata)
        self.assertNotIn("test_count", metadata)
        self.assertEqual(len(events_of_type(events, EVENT_TYPE_CONCERN)), 0)

    def test_the_live_jest_probe_records_no_result(self):
        """Event 46cac0c5a2c9, reconstructed: recorded 0 passed / 3 failed and
        raised blocking concern 66219814e662 while the suite was green."""
        events = self._run(
            "python3 probe.py --arm jest", _LABEL_WITH_A_COUNT.format(arm="jest")
        )
        self._assert_no_result(events)

    def test_the_pytest_twin_records_no_result(self):
        """Same defect, other arm — reproduced from text this thin."""
        events = self._run(
            "python3 probe.py --arm pytest", _LABEL_WITH_A_COUNT.format(arm="pytest")
        )
        self._assert_no_result(events)

    def test_a_real_summary_line_is_still_recorded_and_still_concerns(self):
        """The pairing, through the same hook.

        Without it every assertion above would hold just as well for a parser
        rewired to record nothing at all, and the failure gate would be dead
        rather than honest.
        """
        events = self._run("npx jest", "Tests:  3 failed, 0 passed, 3 total\n")
        metadata = self._test_run_status(events).get("metadata") or {}
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_PARSED)
        self.assertIs(metadata.get("test_passed"), False)
        self.assertEqual(metadata.get("test_count"), 3)
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertEqual(len(concerns), 1)
        self.assertIn("3 failed", concerns[0]["content"])


class TestAFailingRunStillRaises(_BashHookTestCase):
    """AC4/AC5 — the attributing hook keeps its teeth on the same text.

    Both directions of the split live here. `bash_failure` sees a non-zero exit
    the recording hook never sees, so it may read counts the recording hook
    must refuse; the last test runs the identical output through the recording
    hook to pin that it still refuses.
    """

    # Real counts, on no line any arm can anchor on (pytest prints `in Ns` on
    # its summary; this payload has no duration).
    _UNANCHORED_RED = "Exit code 1\n2 failed, 3 passed\n"

    def _fail(self, command: str, error: str):
        bash_failure.run(
            _make_bash_failure_input(command=command, error=error),
            smm_dir=self.smm_dir,
        )
        return events_of_type(self._events(), EVENT_TYPE_CONCERN)

    def test_a_single_failing_run_still_raises_without_any_counts(self):
        """A bare runner's exit code IS the runner's, parseable or not."""
        concerns = self._fail("pytest tests/", "Exit code 1\nSegmentation fault")
        self.assertEqual(len(concerns), 1)
        self.assertIn("pytest", concerns[0]["content"])

    def test_a_compound_failing_run_with_an_unanchored_summary_still_raises(self):
        """`cd dir && runner` is the ordinary teammate shape, and its exit code
        may belong to either segment — so the concern needs the counts."""
        concerns = self._fail("cd app && pytest tests/", self._UNANCHORED_RED)
        self.assertEqual(len(concerns), 1)
        self.assertIn("2 failed", concerns[0]["content"])

    def test_the_same_output_through_the_recording_hook_records_no_counts(self):
        """The story in one assertion pair: same text, two callers, two
        answers, on purpose."""
        bash_post_tool.run(
            _make_bash_input(
                command="cd app && pytest tests/", stdout=self._UNANCHORED_RED
            ),
            smm_dir=self.smm_dir,
        )
        events = self._events()
        metadata = self._test_run_status(events).get("metadata") or {}
        self.assertEqual(metadata.get("parser_status"), PARSER_STATUS_FAILED)
        self.assertNotIn("test_count", metadata)
        self.assertEqual(len(events_of_type(events, EVENT_TYPE_CONCERN)), 0)


if __name__ == "__main__":
    unittest.main()
