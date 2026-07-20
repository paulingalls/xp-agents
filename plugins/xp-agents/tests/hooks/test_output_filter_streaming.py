#!/usr/bin/env python3
"""Tests for teammate_output_filter.py streaming/E2E behavior.

Split from test_output_filter.py to stay under the 500-line cap. Covers
the _PipeStdinMixin real-fd stdin harness, E2E main() over a stream-json
pipe, no-progress timeout configuration, and bulk-burst parsing.
Parsing/formatting unit tests live in test_output_filter_parsing.py.
"""

import contextlib
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase
from event_schema import EVENT_TYPE_STATUS

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


class _PipeStdinMixin:
    """Mixin that gives a test a real-fd stdin via os.pipe().

    Production code calls sys.stdin.fileno() and os.read(); StringIO
    cannot back that, so tests that exercise the streaming filter must
    use a real OS pipe. Mixin handles save/restore of sys.stdin and
    cleanup of fds even when the test raises SystemExit.
    """

    _saved_stdin: object | None = None
    _read_fd: int | None = None
    _write_fd: int | None = None

    def _open_pipe_stdin(self) -> int:
        """Allocate pipe; install fake stdin pointing at the read fd.

        Returns the write fd so the test can feed bytes / close to EOF.
        """
        r, w = os.pipe()
        self._read_fd = r
        self._write_fd = w
        self._saved_stdin = sys.stdin

        read_fd = r

        class _PipeStdin:
            def fileno(self) -> int:
                return read_fd

        sys.stdin = _PipeStdin()  # type: ignore[assignment]
        return w

    def _close_pipe_stdin(self) -> None:
        if self._write_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._write_fd)
            self._write_fd = None
        if self._read_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._read_fd)
            self._read_fd = None
        if self._saved_stdin is not None:
            sys.stdin = self._saved_stdin  # type: ignore[assignment]
            self._saved_stdin = None


class TestMainE2E(_PipeStdinMixin, _HookTestCase):
    """E2E: pipe mock stream-json through main() via real OS pipe.

    Uses a real pipe (not StringIO) because the streaming filter calls
    sys.stdin.fileno() + os.read directly — see _PipeStdinMixin.
    """

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def _feed_eof(self, data: str) -> None:
        """Write data to the pipe and close write end to signal EOF."""
        write_fd = self._open_pipe_stdin()
        os.write(write_fd, data.encode("utf-8"))
        os.close(write_fd)
        self._write_fd = None

    def test_produces_report_and_event(self):
        """main() creates report file and appends SMM event."""
        import teammate_output_filter

        self._feed_eof("\n".join(_MOCK_LINES) + "\n")

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
        import teammate_output_filter

        self._feed_eof(_SYSTEM_LINE + "\n")

        with self.assertRaises(SystemExit) as ctx:
            teammate_output_filter.main(
                smm_dir=self.smm_dir,
                teammate_id="teammate-step-1",
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_clears_coordination_on_completion(self):
        """Teammate coordination entry cleared after stream processing."""
        import coordination
        import teammate_output_filter

        coordination.update_coordination(
            self.smm_dir, "teammate-step-1", ["src/auth.py"]
        )
        coord = coordination.read_coordination(self.smm_dir)
        self.assertIn("teammate-step-1", coord)

        self._feed_eof("\n".join(_MOCK_LINES) + "\n")

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


class TestNoProgressTimeout(unittest.TestCase):
    """Primary liveness is the spawn watchdog's job, not the filter's. A filter
    deadline SHORTER than the 900s watchdog preempts it and kills teammates
    during legitimately silent tool calls (nested reviews, acceptance runs). So
    the default deadline is set LONGER than the watchdog window — it never
    preempts the watchdog yet still backstops a spawn-side wedge where the stream
    neither advances nor EOFs. XP_TEAMMATE_FILTER_TIMEOUT overrides; "0" (or any
    value <= 0) disables the deadline entirely.
    """

    def test_read_timeout_defaults_to_watchdog_backstop(self):
        """Unset env → a backstop deadline strictly longer than the watchdog
        window so the watchdog always forces EOF first."""
        import teammate_output_filter
        import teammate_runner

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_FILTER_TIMEOUT", None)
            timeout = teammate_output_filter._read_timeout()
        assert timeout is not None
        self.assertGreater(
            timeout,
            teammate_runner._WATCHDOG_TIMEOUT_S,
            "filter default must exceed the watchdog window so it never preempts it",
        )

    def test_read_timeout_empty_string_defaults_to_backstop(self):
        """An empty override string is treated as unset (default backstop)."""
        import teammate_output_filter

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": ""}):
            self.assertEqual(
                teammate_output_filter._read_timeout(),
                teammate_output_filter._DEFAULT_READ_TIMEOUT_S,
            )

    def test_read_timeout_zero_disables_deadline(self):
        """ "0" is an explicit opt-out (no deadline), NOT an instant-timeout that
        would abort a healthy run on a non-blocking select poll."""
        import teammate_output_filter

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": "0"}):
            self.assertIsNone(teammate_output_filter._read_timeout())

    def test_read_timeout_negative_disables_deadline(self):
        import teammate_output_filter

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": "-5"}):
            self.assertIsNone(teammate_output_filter._read_timeout())

    def test_read_timeout_env_override(self):
        import teammate_output_filter

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": "0.2"}):
            self.assertEqual(teammate_output_filter._read_timeout(), 0.2)

    def test_read_timeout_malformed_falls_back_not_crash(self):
        """A malformed override must not raise (the filter is the teammate's
        sole stdout reader — a crash here re-deadlocks the run); fall back to
        the backstop default."""
        import teammate_output_filter

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": "600s"}):
            self.assertEqual(
                teammate_output_filter._read_timeout(),
                teammate_output_filter._DEFAULT_READ_TIMEOUT_S,
            )


class TestStreamingTimeout(_PipeStdinMixin, _HookTestCase):
    """Silent-stdin handling: the default backstop deadline is far longer than
    any test window, so a silent pipe effectively blocks until EOF; an explicit
    short opt-in env deadline still fires as a backstop."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def test_silent_pipe_blocks_without_timeout_then_exits_on_eof(self):
        """With only the (long) default deadline, a silent pipe does NOT time
        the filter out within any realistic window — it blocks. Only EOF (which
        the watchdog guarantees by killing claude) ends the read, exiting 1 with
        the no-result diagnostic."""
        import teammate_output_filter

        write_fd = self._open_pipe_stdin()
        os.write(write_fd, (_SYSTEM_LINE + "\n").encode("utf-8"))

        outcome: dict = {}

        def run():
            try:
                teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")
            except SystemExit as exc:
                outcome["code"] = exc.code

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XP_TEAMMATE_FILTER_TIMEOUT", None)
            t = threading.Thread(target=run, daemon=True)
            t.start()
            time.sleep(0.3)
            self.assertTrue(
                t.is_alive(), "filter must block on a silent pipe, not exit"
            )
            os.close(write_fd)  # EOF
            self._write_fd = None
            t.join(timeout=3)

        self.assertFalse(t.is_alive(), "filter must exit once the stream EOFs")
        self.assertEqual(outcome.get("code"), 1)

    def test_opt_in_timeout_still_exits_on_silent_pipe(self):
        """Backstop: an explicit XP_TEAMMATE_FILTER_TIMEOUT actually fires.

        This is a semantic DEADLINE, not a CPU benchmark -- time is the behaviour
        under test, so it stays time-based. Both bounds are expressed against the
        configured timeout rather than a magic constant:

        - lower: the filter must WAIT for the deadline. Nothing asserted this
          before, so a filter that ignored the timeout and exited instantly passed.
        - upper: catches a deadline that fires LATE -- a units/slack/multiplier
          bug that stretches the configured wait. It deliberately does NOT guard
          the block-to-EOF regression: this test holds the pipe's write end open,
          so a filter that blocked for EOF (or fell back to the ~20min default
          backstop) would never return, and the runner would HANG here rather
          than fail this bound. The bound is loose for the failures it can see;
          a tight one would just re-import machine load into the gate.
        """
        import teammate_output_filter

        timeout = 0.2

        write_fd = self._open_pipe_stdin()
        os.write(write_fd, (_SYSTEM_LINE + "\n").encode("utf-8"))

        with patch.dict(os.environ, {"XP_TEAMMATE_FILTER_TIMEOUT": str(timeout)}):
            start = time.monotonic()
            with self.assertRaises(SystemExit) as ctx:
                teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")
            elapsed = time.monotonic() - start

        self.assertEqual(ctx.exception.code, 1)
        self.assertGreaterEqual(
            elapsed,
            timeout,
            f"filter exited after {elapsed:.2f}s, before its {timeout}s deadline -- "
            "it is not waiting on the timeout at all",
        )
        self.assertLess(
            elapsed,
            timeout * 10,
            f"filter waited {elapsed:.2f}s on a silent pipe -- more than 10x its "
            f"{timeout}s deadline, so the configured value is being scaled or "
            "padded rather than honoured",
        )


class TestStreamingBurst(_PipeStdinMixin, _HookTestCase):
    """Filter parses a single >8KB bulk write without losing the result event."""

    def tearDown(self):
        self._close_pipe_stdin()
        super().tearDown()

    def test_parses_bulk_burst_and_captures_result(self):
        import teammate_output_filter

        # 200 realistic stream-json lines, ~50B each → ~10KB > 8KB threshold.
        # Single os.write must fit in pipe buffer (16KB+ on macOS/Linux).
        filler = json.dumps({"type": "assistant", "message": {"text": "x" * 10}})
        bulk_lines = [filler] * 200 + [_RESULT_LINE]
        bulk = ("\n".join(bulk_lines) + "\n").encode("utf-8")
        self.assertGreater(len(bulk), 8192, "Need >8KB to exercise buffered case")

        write_fd = self._open_pipe_stdin()
        os.write(write_fd, bulk)
        os.close(write_fd)
        self._write_fd = None  # already closed; signals EOF to reader

        with patch(
            "teammate_output_filter.get_current_branch",
            return_value="teammate-step-1",
        ):
            teammate_output_filter.process_stream(self.smm_dir, "teammate-step-1")

        report = self.smm_dir / ".teammate-report-teammate-step-1.txt"
        self.assertTrue(report.is_file(), "Report file not written")
        self.assertIn("story-001", report.read_text())

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], EVENT_TYPE_STATUS)
        self.assertIn("0.32", events[0]["content"])


if __name__ == "__main__":
    unittest.main()
