#!/usr/bin/env python3
"""Tests for teammate_output_filter.py's captured-stream diagnostic dump.

A no-result stream (EOF or progress-timeout) persists every captured line to
a `.teammate-stream-{name}.log` artifact so evidence that would otherwise be
described-then-discarded survives for inspection. Covers: EOF mode, timeout
mode, the no-artifact-on-success invariant, and head+tail retention over the
line cap. Uses the shared real-fd `_PipeStdinMixin` from
tests/_stream_stdin_fixtures.py (StringIO cannot back the fd-based reader).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _PipeStdinMixin

_SYSTEM_LINE = json.dumps(
    {
        "type": "system",
        "subtype": "init",
        "model": "claude-sonnet-4-6",
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


class TestStreamDumpOnEOF(_PipeStdinMixin, _HookTestCase):
    """A no-result stream that ends at EOF (no timeout) persists the capture
    and names the mode explicitly -- the ambiguity (EOF only implied by the
    ABSENCE of the timeout prefix) is exactly what made the two prior
    failures unreadable."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def test_eof_no_result_writes_dump_and_names_path(self):
        import teammate_output_filter
        import worktree

        self._feed_eof(_SYSTEM_LINE + "\nWARN: unrecognized spawn-side text\n")

        with self.assertRaises(SystemExit) as ctx:
            teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")

        self.assertEqual(ctx.exception.code, 1)

        dump_path = worktree.teammate_stream_dump_path(self.smm_dir, "teammate-step-1")
        self.assertTrue(dump_path.is_file(), "stream dump artifact should be written")
        self.assertIn("WARN: unrecognized spawn-side text", dump_path.read_text())

    def test_eof_message_states_mode_and_artifact_path(self):
        import contextlib
        import io

        import teammate_output_filter
        import worktree

        self._feed_eof(_SYSTEM_LINE + "\n")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")

        message = stderr.getvalue()
        self.assertIn("EOF", message)
        dump_path = worktree.teammate_stream_dump_path(self.smm_dir, "teammate-step-1")
        self.assertIn(str(dump_path), message)


class TestStreamDumpOnTimeout(_PipeStdinMixin, _HookTestCase):
    """The progress-timeout no-result path persists the capture identically
    and names its mode as a timeout, not EOF."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def test_timeout_no_result_writes_dump_and_states_timeout(self):
        import contextlib
        import io

        import teammate_output_filter
        import worktree

        write_fd = self._open_pipe_stdin()
        os.write(write_fd, (_SYSTEM_LINE + "\n").encode("utf-8"))

        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": "0.2"}),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as ctx,
        ):
            teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")

        self.assertEqual(ctx.exception.code, 1)
        message = stderr.getvalue()
        self.assertIn("imeout", message)  # "Timeout"/"timeout" mode wording
        self.assertNotIn("EOF", message)

        dump_path = worktree.teammate_stream_dump_path(self.smm_dir, "teammate-step-1")
        self.assertTrue(dump_path.is_file())
        self.assertIn(_SYSTEM_LINE, dump_path.read_text())
        self.assertIn(str(dump_path), message)


class TestNoDumpOnSuccess(_PipeStdinMixin, _HookTestCase):
    """A stream that produces a result event writes NO artifact and leaves
    the existing summary output unchanged."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def test_successful_stream_writes_no_dump(self):
        import teammate_output_filter
        import worktree

        self._feed_eof(_SYSTEM_LINE + "\n" + _RESULT_LINE + "\n")

        with patch(
            "teammate_output_filter.get_current_branch",
            return_value="teammate-step-1",
        ):
            teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")

        dump_path = worktree.teammate_stream_dump_path(self.smm_dir, "teammate-step-1")
        self.assertFalse(dump_path.exists(), "no artifact should be written on success")

        report = self.smm_dir / ".teammate-report-teammate-step-1.txt"
        self.assertTrue(report.is_file())


class TestStreamDumpRetention(unittest.TestCase):
    """Over-cap captures keep HEAD and TAIL, not tail alone -- a refusal or
    WARN printed first and then buried under noise is exactly the case this
    story surfaces, and tail-only retention would elide it."""

    def test_over_cap_capture_keeps_head_and_tail_with_elided_count(self):
        import teammate_output_filter

        lines = [f"line-{i}" for i in range(700)]
        lines[0] = "FIRST-LINE-MARKER"
        lines[-1] = "LAST-LINE-MARKER"

        dump = teammate_output_filter._compose_stream_dump(
            lines,
            mode="eof",
            timeout=None,
            parsed_count=0,
            total_count=len(lines),
        )

        self.assertIn("FIRST-LINE-MARKER", dump)
        self.assertIn("LAST-LINE-MARKER", dump)
        elided = len(lines) - teammate_output_filter._STREAM_DUMP_MAX_LINES
        self.assertIn(str(elided), dump)


if __name__ == "__main__":
    unittest.main()
