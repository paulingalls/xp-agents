#!/usr/bin/env python3
"""A teammate that died must not be reported as one that finished.

`process_stream` took the success path for ANY terminal result event. A
teammate killed by an API drop mid-edit exits 0 with `is_error: true` and a
report file holding nothing but the error string, and the lead was handed
`Report: … | Cost: $8.86` — the success shape. That is how one teammate's
death went unnoticed while the lead ran acceptance against its half-finished
branch.

Every failure assertion here is paired with the success control that uses the
SAME call, differing only in the result event. A death test that passed
because the function always says "failed" would delete the reporting the
filter exists for, and only the pair catches that.

Its own file rather than test_teammate_runner.py, which is at 493 lines
against the hard 500-line cap — that one fails the build rather than the
ratchet.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import teammate_output_filter
from conftest import _HookTestCase, _PipeStdinMixin

TEAMMATE = "worktree-story-042"

#: What a teammate that finished looks like.
SUCCESS_RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "total_cost_usd": 0.32,
    "duration_ms": 192000,
    "num_turns": 45,
    "result": "Implemented story-042.",
}

#: What the API drop mid-edit actually looked like: exit 0, is_error true, and
#: a `result` carrying only the error string.
DEATH_RESULT = {
    "type": "result",
    "subtype": "error_during_execution",
    "is_error": True,
    "total_cost_usd": 8.86,
    "duration_ms": 1_920_000,
    "num_turns": 210,
    "result": "API Error: Connection error.",
}


def _line(event: dict) -> str:
    return json.dumps(event)


class TestTheFailureSignalIsRead(unittest.TestCase):
    """Which terminal events count as a death.

    Two independent signals, and either alone is enough: `is_error` is the
    flag, `subtype` names WHICH failure and is the half worth printing. A
    harness that sets one and not the other must not slip through — that is
    the whole defect.
    """

    def test_a_success_result_has_no_failure_reason(self):
        self.assertIsNone(teammate_output_filter.failure_reason(SUCCESS_RESULT))

    def test_the_error_flag_and_subtype_together_name_the_reason(self):
        self.assertEqual(
            teammate_output_filter.failure_reason(DEATH_RESULT),
            "error_during_execution",
        )

    def test_a_non_success_subtype_alone_is_a_failure(self):
        """`error_max_turns` is a real terminal reason. Requiring `is_error`
        as well would let a harness that sets only one read as success."""
        reason = teammate_output_filter.failure_reason(
            {"type": "result", "subtype": "error_max_turns"}
        )
        self.assertEqual(reason, "error_max_turns")

    def test_the_error_flag_alone_is_a_failure(self):
        reason = teammate_output_filter.failure_reason(
            {"type": "result", "is_error": True}
        )
        self.assertIsNotNone(reason)

    def test_a_result_carrying_neither_signal_is_a_success(self):
        """Absence of both is not evidence of death — an older or simpler
        harness emits a bare terminal event, and refusing those would report
        every such run as failed."""
        self.assertIsNone(teammate_output_filter.failure_reason({"type": "result"}))


class TestTheSummaryLine(unittest.TestCase):
    """AC-3. The one line the lead actually reads."""

    def _summary(self, failure: str | None) -> str:
        return teammate_output_filter.format_summary(
            Path("/smm/.teammate-report-x.txt"), "story-042", 8.86, failure=failure
        )

    def test_a_death_does_not_render_the_success_shape(self):
        self.assertFalse(self._summary("error_during_execution").startswith("Report:"))

    def test_a_death_names_the_reason(self):
        self.assertIn("error_during_execution", self._summary("error_during_execution"))

    def test_a_death_says_it_failed(self):
        self.assertIn("FAILED", self._summary("error_during_execution"))

    def test_the_success_shape_is_unchanged(self):
        """Control. Without it, "always print FAILED" passes everything
        above while destroying the line the lead reads on every good run."""
        summary = self._summary(None)
        self.assertTrue(summary.startswith("Report: "))
        self.assertNotIn("FAILED", summary)
        self.assertIn("Cost: $8.86", summary)


class TestTheReportFile(_HookTestCase):
    """The artifact the lead opens after the line tells it to."""

    def test_a_death_is_named_at_the_top_of_the_report(self):
        """The report holds only the error string on this path, and an error
        string alone reads like a note the teammate chose to leave."""
        path = teammate_output_filter.write_report(
            self.smm_dir, TEAMMATE, "API Error: Connection error.", failure="boom"
        )
        text = path.read_text()
        self.assertIn("FAILED", text.splitlines()[0])
        self.assertIn("boom", text.splitlines()[0])

    def test_the_error_string_itself_is_preserved(self):
        path = teammate_output_filter.write_report(
            self.smm_dir, TEAMMATE, "API Error: Connection error.", failure="boom"
        )
        self.assertIn("API Error: Connection error.", path.read_text())

    def test_a_successful_report_is_written_verbatim(self):
        """Control: no header, no wrapper, byte-for-byte what the teammate
        said. The lead's close reads this file."""
        path = teammate_output_filter.write_report(
            self.smm_dir, TEAMMATE, "Implemented story-042."
        )
        self.assertEqual(path.read_text(), "Implemented story-042.")


class TestTheCompletionEvent(_HookTestCase):
    """A death still records what it cost.

    The money was spent and the turns were taken — dropping them would hide a
    $8.86 failure from every cost and velocity reading. What must change is
    the claim: "completed" is not true of a run that died.
    """

    def _event(self, result: dict, failure: str | None) -> dict:
        teammate_output_filter.record_completion(
            self.smm_dir, TEAMMATE, result, failure=failure
        )
        lines = (self.smm_dir / "events.jsonl").read_text().strip().splitlines()
        return json.loads(lines[-1])

    def test_a_death_records_its_cost_and_turns(self):
        event = self._event(DEATH_RESULT, "error_during_execution")
        self.assertAlmostEqual(event["metadata"]["cost_usd"], 8.86)
        self.assertEqual(event["metadata"]["turns"], 210)

    def test_a_death_does_not_claim_completion(self):
        event = self._event(DEATH_RESULT, "error_during_execution")
        self.assertNotIn("completed", event["content"])
        self.assertIn("error_during_execution", event["content"])

    def test_a_death_is_flagged_in_metadata(self):
        """Prose is for humans; a reader that aggregates needs a field."""
        event = self._event(DEATH_RESULT, "error_during_execution")
        self.assertTrue(event["metadata"]["failed"])

    def test_a_completion_still_says_completed(self):
        """Control."""
        event = self._event(SUCCESS_RESULT, None)
        self.assertIn("completed", event["content"])
        self.assertNotIn("failed", event["metadata"])


class TestProcessStreamOnADeath(_PipeStdinMixin, _HookTestCase):
    """The whole path, driven through a real pipe as the spawn drives it."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def _run(self, result: dict) -> None:
        self._feed_eof(_line(result) + "\n")
        with patch.object(
            teammate_output_filter, "get_current_branch", return_value="story-042"
        ):
            teammate_output_filter.process_stream(self.smm_dir, TEAMMATE)

    def test_a_death_exits_non_zero(self):
        """Exiting 0 is exactly what hid the earlier death: the spawn saw a
        clean exit and the lead ran acceptance against the branch."""
        with self.assertRaises(SystemExit) as ctx:
            self._run(DEATH_RESULT)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_a_completion_does_not_exit_non_zero(self):
        """Control. Without it, `sys.exit(1)` on every path passes above."""
        self._run(SUCCESS_RESULT)

    def test_a_death_prints_a_failure_line_not_the_success_shape(self):
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            self.assertRaises(SystemExit),
        ):
            self._run(DEATH_RESULT)
        printed = out.getvalue() + err.getvalue()
        self.assertIn("FAILED", printed)
        self.assertIn("error_during_execution", printed)
        self.assertFalse(out.getvalue().startswith("Report:"))

    def test_a_death_still_writes_the_report_and_the_event(self):
        with self.assertRaises(SystemExit):
            self._run(DEATH_RESULT)
        report = self.smm_dir / f".teammate-report-{TEAMMATE}.txt"
        self.assertIn("API Error", report.read_text())
        self.assertTrue((self.smm_dir / "events.jsonl").read_text().strip())

    def test_a_death_clears_the_coordination_entry(self):
        """The process is gone, and this filter watched it go. Left behind,
        the entry pins its files against every other agent — and its
        heartbeat is FRESH at the moment of death, so the liveness leg would
        read it as a working teammate for hours."""
        coordination.update_coordination(self.smm_dir, TEAMMATE, ["src/auth.py"])
        with self.assertRaises(SystemExit):
            self._run(DEATH_RESULT)
        self.assertNotIn(
            TEAMMATE,
            coordination.read_coordination(self.smm_dir, max_age_seconds=10**9),
        )


if __name__ == "__main__":
    unittest.main()
