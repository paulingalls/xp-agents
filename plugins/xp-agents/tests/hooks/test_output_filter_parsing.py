#!/usr/bin/env python3
"""Tests for teammate_output_filter.py parsing/formatting units.

Split from test_output_filter.py to stay under the 500-line cap. Covers
parse_result_event, write_report, record_completion, format_summary, and
extract_diagnostics — pure/small-fixture units, no stdin piping involved.
Streaming/E2E pipe-based tests live in test_output_filter_streaming.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase
from event_schema import EVENT_TYPE_STATUS
from spawn_prompt import REFUSAL_PREFIX as _REFUSAL_PREFIX

_SYSTEM_LINE = json.dumps(
    {
        "type": "system",
        "subtype": "init",
        "model": "claude-sonnet-4-6",
    }
)

_ASSISTANT_LINE = json.dumps(
    {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Working"}]},
    }
)

_RESULT_LINE = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.32,
        "duration_ms": 192000,
        "num_turns": 45,
        "result": "Implemented story-001 successfully.",
    }
)

_MOCK_LINES = [_SYSTEM_LINE, _ASSISTANT_LINE, _RESULT_LINE]


class TestIsResult(unittest.TestCase):
    """_is_result is the single terminal-event predicate shared by both detection paths.

    (invariant: `parse_result_event` and `_consume_stream` agree on what 'result' means)
    """

    def test_true_for_result_event(self):
        import teammate_output_filter

        self.assertTrue(teammate_output_filter._is_result({"type": "result"}))

    def test_false_for_non_result(self):
        import teammate_output_filter

        self.assertFalse(teammate_output_filter._is_result({"type": "system"}))
        self.assertFalse(teammate_output_filter._is_result({"type": "assistant"}))

    def test_false_for_missing_type(self):
        import teammate_output_filter

        self.assertFalse(teammate_output_filter._is_result({}))
        self.assertFalse(teammate_output_filter._is_result({"reason": "x"}))


class TestParseResultEvent(unittest.TestCase):
    """parse_result_event finds type:result in stream-json lines."""

    def test_finds_result_event(self):
        """Extracts result event from mixed stream-json lines."""
        import teammate_output_filter

        result = teammate_output_filter.parse_result_event(_MOCK_LINES)
        assert result is not None
        self.assertAlmostEqual(result["total_cost_usd"], 0.32)
        self.assertEqual(result["duration_ms"], 192000)
        self.assertEqual(result["num_turns"], 45)
        self.assertIn("story-001", result["result"])

    def test_returns_none_when_no_result(self):
        """Returns None when no type:result event in stream."""
        import teammate_output_filter

        lines = [_SYSTEM_LINE, _ASSISTANT_LINE]
        result = teammate_output_filter.parse_result_event(lines)
        self.assertIsNone(result)

    def test_handles_malformed_json_lines(self):
        """Skips malformed lines without crashing."""
        import teammate_output_filter

        lines = ["not json", "{bad", _RESULT_LINE]
        result = teammate_output_filter.parse_result_event(lines)
        assert result is not None

    def test_handles_empty_input(self):
        """Returns None for empty input."""
        import teammate_output_filter

        result = teammate_output_filter.parse_result_event([])
        self.assertIsNone(result)


class TestWriteReport(_HookTestCase):
    """write_report creates correct file with result text."""

    def test_creates_report_file(self):
        """Report file created at correct path."""
        import teammate_output_filter

        path = teammate_output_filter.write_report(
            self.smm_dir, "teammate-step-1", "Done."
        )
        expected = self.smm_dir / ".teammate-report-teammate-step-1.txt"
        self.assertEqual(path, expected)
        self.assertTrue(path.is_file())

    def test_report_contains_result_text(self):
        """Report file contains the result text."""
        import teammate_output_filter

        path = teammate_output_filter.write_report(
            self.smm_dir, "teammate-step-2", "All criteria met."
        )
        self.assertEqual(path.read_text(), "All criteria met.")


class TestRecordCompletion(_HookTestCase):
    """record_completion appends event with correct metadata."""

    def test_appends_event_with_cost_metadata(self):
        """Event has cost_usd, turns, duration_ms in metadata."""
        import teammate_output_filter

        result = {
            "total_cost_usd": 0.32,
            "num_turns": 45,
            "duration_ms": 192000,
        }
        teammate_output_filter.record_completion(
            self.smm_dir,
            "teammate-step-1",
            result,
        )
        events = self._read_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], EVENT_TYPE_STATUS)
        self.assertIn("0.32", event["content"])
        self.assertIn("45", event["content"])
        meta = event.get("metadata", {})
        self.assertAlmostEqual(meta["cost_usd"], 0.32)
        self.assertEqual(meta["turns"], 45)
        self.assertEqual(meta["duration_ms"], 192000)

    def test_event_agent_id_is_teammate(self):
        """Event agent_id matches the teammate ID."""
        import teammate_output_filter

        result = {
            "total_cost_usd": 0.10,
            "num_turns": 10,
            "duration_ms": 60000,
        }
        teammate_output_filter.record_completion(
            self.smm_dir,
            "teammate-step-3",
            result,
        )
        events = self._read_events()
        self.assertEqual(events[0]["agent_id"], "teammate-step-3")


class TestFormatSummary(unittest.TestCase):
    """format_summary produces one-line stdout summary."""

    def test_includes_report_path(self):
        """Summary contains the report file path."""
        import teammate_output_filter

        summary = teammate_output_filter.format_summary(
            Path("/smm/.teammate-report-step-1.txt"),
            "teammate-step-1",
            0.32,
        )
        self.assertIn(".teammate-report-step-1.txt", summary)

    def test_includes_branch_and_cost(self):
        """Summary contains branch name and cost."""
        import teammate_output_filter

        summary = teammate_output_filter.format_summary(
            Path("/smm/report.txt"),
            "teammate-step-1",
            0.32,
        )
        self.assertIn("teammate-step-1", summary)
        self.assertIn("0.32", summary)


_BLOCK_LINE = json.dumps(
    {
        "type": "system",
        "subtype": "hook_block",
        "decision": "block",
        "reason": "Session kickoff required. Run /xp-kickoff.",
    }
)


class TestExtractDiagnostics(unittest.TestCase):
    """extract_diagnostics surfaces block events and errors from stream-json."""

    def test_finds_block_event(self):
        """Extracts block reason from a hook_block system event."""
        import teammate_output_filter

        lines = [_SYSTEM_LINE, _BLOCK_LINE]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("kickoff", diags.lower())

    def test_empty_stream_returns_generic_message(self):
        """Returns a useful message when stream is empty."""
        import teammate_output_filter

        diags = teammate_output_filter.extract_diagnostics([])
        self.assertIn("no output", diags.lower())

    def test_no_block_returns_line_count(self):
        """When no block found, reports number of lines processed."""
        import teammate_output_filter

        lines = [_SYSTEM_LINE, _ASSISTANT_LINE]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("2", diags)

    def test_finds_decision_block_in_result(self):
        """Extracts block reason from top-level decision:block JSON."""
        import teammate_output_filter

        block = json.dumps({"decision": "block", "reason": "Blocked by gate"})
        diags = teammate_output_filter.extract_diagnostics([block])
        self.assertIn("Blocked by gate", diags)

    def test_multiple_blocks_joined(self):
        """Multiple block events are joined with semicolons."""
        import teammate_output_filter

        b1 = json.dumps({"decision": "block", "reason": "Gate A"})
        b2 = json.dumps({"decision": "block", "reason": "Gate B"})
        diags = teammate_output_filter.extract_diagnostics([b1, b2])
        self.assertIn("Gate A", diags)
        self.assertIn("Gate B", diags)
        self.assertIn(";", diags)

    def test_surfaces_python_traceback(self):
        """Non-JSON traceback lines appear in diagnostics."""
        import teammate_output_filter

        lines = [
            "Traceback (most recent call last):",
            '  File "spawn_teammate.py", line 110, in main',
            "ModuleNotFoundError: No module named '_append_impl'",
        ]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("ModuleNotFoundError", diags)

    def test_surfaces_git_fatal(self):
        """Git fatal errors appear in diagnostics."""
        import teammate_output_filter

        lines = ["fatal: not a git repository"]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("fatal:", diags)

    def test_surfaces_unrecognized_non_json_lines(self):
        """Non-JSON lines matching no known error signal are surfaced rather
        than dropped -- the exact failure mode behind concern bed429ee8018:
        the two 7-line captures were spawn-side text, not stream-json, and
        got silently discarded instead of shown to the lead."""
        import teammate_output_filter

        lines = [
            "WARN: falling back to /tmp for worktree base",
            "Spawning teammate in worktree ...",
        ]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("WARN: falling back to /tmp for worktree base", diags)
        self.assertIn("Spawning teammate in worktree ...", diags)

    def test_spawn_notice_is_not_reported_as_the_failure_cause(self):
        """The spawn's own advisories ride the same 2>&1 pipe as the teammate's
        stdout, and the model one fires on every untiered spawn. Left in the
        evidence tier they outranked the no-result fallback and became the
        reported cause of every no-result failure — a tier notice shown for a
        watchdog kill, sending the lead after a --model problem that isn't."""
        import spawn_command
        import teammate_output_filter

        lines = [
            _SYSTEM_LINE,
            f"{spawn_command.NOTICE_PREFIX}no model resolved — teammate tier is "
            "inherited from the orchestrator",
        ]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertNotIn("no model resolved", diags)
        self.assertIn("No result event", diags)

    def test_a_real_diagnostic_still_outranks_a_notice(self):
        """Demoting the notice must not demote the line beside it."""
        import spawn_command
        import teammate_output_filter

        lines = [
            f"{spawn_command.NOTICE_PREFIX}no model resolved",
            "worktree base is read-only",
        ]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("worktree base is read-only", diags)
        self.assertNotIn("no model resolved", diags)

    def test_mixed_json_and_unrecognized_reports_both_counts_not_stream_json(self):
        """A mix of parsed JSON and unrecognized non-JSON text reports the
        parsed-event count and the raw line count as distinct figures, and
        must not describe the unparsed line as stream-json."""
        import teammate_output_filter

        lines = [_SYSTEM_LINE, "some spawn-side diagnostic text", _ASSISTANT_LINE]
        diags = teammate_output_filter.extract_diagnostics(lines)
        self.assertIn("some spawn-side diagnostic text", diags)
        # Assert the counts as one phrase: a bare assertIn("2") would pass on
        # any stray 2 anywhere in the message, including inside a quoted line.
        self.assertIn("1 of 3 line(s) captured, 2 parsed as stream-json", diags)

    def test_scalar_json_line_is_treated_as_non_stream_json(self):
        """A line that is valid JSON but NOT an object (a bare number, string,
        or null) is spawn-side text, not a stream-json event. It must be
        surfaced as unrecognized output — never fed to `.get()`, which raises
        AttributeError and kills the filter, the teammate's sole stdout
        reader, losing the whole capture on the very path that exists to
        preserve it."""
        import teammate_output_filter

        for scalar in ("7", '"just a quoted string"', "null", "[1, 2]"):
            with self.subTest(scalar=scalar):
                diags = teammate_output_filter.extract_diagnostics(
                    [_SYSTEM_LINE, scalar]
                )
                self.assertIn(scalar, diags)
                self.assertIn("1 of 2 line(s) captured, 1 parsed", diags)

    def test_long_unrecognized_line_is_truncated_in_the_message(self):
        """A single unrecognized line is bounded in LENGTH, not just count.

        The reader yields any unterminated trailing fragment at EOF, so an
        abrupt mid-line EOF -- the very failure this diagnostic serves -- can
        hand back a read-chunk-sized line. Quoting it whole would dump ~64KB
        into the lead's context; the artifact keeps the verbatim text, the
        message keeps only the shape."""
        import teammate_output_filter

        giant = '{"type":"assistant","message":' + "x" * 60000
        diags = teammate_output_filter.extract_diagnostics([giant])
        self.assertLess(len(diags), 1000)
        self.assertIn('{"type":"assistant","message":', diags)
        self.assertIn("truncated", diags)

    def test_recognized_error_line_keeps_a_full_refusal(self):
        """The refusal's remedy sits ~450 chars into a single line, so the
        recognised-signal tier must quote it whole -- truncation there would
        drop the path and the fix, the contract test_spawn_prompt_guard
        pins."""
        import teammate_output_filter

        refusal = f"{_REFUSAL_PREFIX} story-001: " + "detail " * 100 + "re-run."
        diags = teammate_output_filter.extract_diagnostics([refusal])
        self.assertIn(refusal, diags)

    def test_truncated_json_carrying_an_error_signal_is_still_bounded(self):
        """The recognised-signal tier is LOOSELY bounded, not unbounded.

        A stream severed mid-line inside a large assistant event yields the
        whole unterminated fragment at EOF (the very failure this diagnostic
        serves). It does not parse, so it reaches the non-JSON tiers -- and if
        its text carries an "Error:" it lands in the error tier. Quoting that
        whole would dump ~64KB into the lead's context; the artifact keeps the
        verbatim bytes, the message keeps the shape.
        """
        import teammate_output_filter

        giant = '{"type":"assistant","message":"Error: ' + "x" * 60000
        diags = teammate_output_filter.extract_diagnostics([giant])
        self.assertLess(len(diags), 4000)
        self.assertIn("truncated", diags)
        self.assertIn('{"type":"assistant","message":"Error: ', diags)

    def test_consume_stream_survives_scalar_json_line(self):
        """The fd-side reader shares the object predicate: a scalar JSON line
        must not crash _consume_stream before extract_diagnostics ever runs."""
        import teammate_output_filter

        self.assertIsNone(teammate_output_filter.parse_result_event(["7", "null"]))


if __name__ == "__main__":
    unittest.main()
