#!/usr/bin/env python3
"""Tests for teammate_output_filter.py — stream-json result capture.

Covers: parse_result_event, write_report, record_completion,
format_summary, E2E main() pipe.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase

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


class TestParseResultEvent(unittest.TestCase):
    """parse_result_event finds type:result in stream-json lines."""

    def test_finds_result_event(self):
        """Extracts result event from mixed stream-json lines."""
        import teammate_output_filter

        result = teammate_output_filter.parse_result_event(_MOCK_LINES)
        self.assertIsNotNone(result)
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
        self.assertIsNotNone(result)

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
        self.assertEqual(event["type"], "status")
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


class TestMainE2E(_HookTestCase):
    """E2E: pipe mock stream-json through main()."""

    def test_produces_report_and_event(self):
        """main() creates report file and appends SMM event."""
        import io

        import teammate_output_filter

        stdin_data = "\n".join(_MOCK_LINES) + "\n"
        sys.stdin = io.StringIO(stdin_data)

        with patch(
            "teammate_output_filter.get_current_branch",
            return_value="teammate-step-1",
        ):
            teammate_output_filter.main(
                smm_dir=self.smm_dir,
                teammate_id="teammate-step-1",
            )

        report = self.smm_dir / ".teammate-report-teammate-step-1.txt"
        self.assertTrue(report.is_file())
        self.assertIn("story-001", report.read_text())

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertIn("0.32", events[0]["content"])

    def test_exits_with_error_on_no_result(self):
        """main() raises SystemExit when no result event."""
        import io

        import teammate_output_filter

        stdin_data = _SYSTEM_LINE + "\n"
        sys.stdin = io.StringIO(stdin_data)

        with self.assertRaises(SystemExit) as ctx:
            teammate_output_filter.main(
                smm_dir=self.smm_dir,
                teammate_id="teammate-step-1",
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_clears_coordination_on_completion(self):
        """Teammate coordination entry cleared after stream processing."""
        import io

        import coordination
        import teammate_output_filter

        coordination.update_coordination(
            self.smm_dir, "teammate-step-1", ["src/auth.py"]
        )
        coord = coordination.read_coordination(self.smm_dir)
        self.assertIn("teammate-step-1", coord)

        stdin_data = "\n".join(_MOCK_LINES) + "\n"
        sys.stdin = io.StringIO(stdin_data)

        with patch(
            "teammate_output_filter.get_current_branch",
            return_value="teammate-step-1",
        ):
            teammate_output_filter.main(
                smm_dir=self.smm_dir,
                teammate_id="teammate-step-1",
            )

        coord = coordination.read_coordination(self.smm_dir)
        self.assertNotIn(
            "teammate-step-1",
            coord,
            "Coordination entry should be cleared after completion",
        )


if __name__ == "__main__":
    unittest.main()
