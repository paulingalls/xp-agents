#!/usr/bin/env python3
"""Shared real-fd stdin fixture for the streaming output-filter tests.

`teammate_output_filter.process_stream` drives `sys.stdin.fileno()` +
`os.read()` + `select()` directly (a buffered TextIOWrapper deadlocks under
select), so a StringIO cannot back it — a test that exercises the filter needs
a real OS pipe. `_PipeStdinMixin` owns that pipe: allocate, install a fake
stdin whose only job is to report the read fd, and restore/close in tearDown
even when the test raises SystemExit.

Promoted from two byte-identical inline copies (`hooks/test_output_filter_
streaming.py` and `hooks/test_output_filter_stream_dump.py`) so a third
streaming test file doesn't paste a third. Pinned by
`tests/integration/test_conftest_consolidation_pin.py
::test_single_pipe_stdin_mixin_definition`.
"""

import contextlib
import os
import sys

__all__ = ["_PipeStdinMixin"]


class _PipeStdinMixin:
    """Mixin that gives a test a real-fd stdin via os.pipe().

    Subclasses call `self._feed_eof(data)` for a stream that ends at EOF, or
    `self._open_pipe_stdin()` directly when they need to hold the write end
    open (the progress-timeout path). Every subclass must call
    `self._close_pipe_stdin()` from tearDown.
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

    def _feed_eof(self, data: str) -> None:
        """Write data to the pipe and close the write end to signal EOF."""
        write_fd = self._open_pipe_stdin()
        os.write(write_fd, data.encode("utf-8"))
        os.close(write_fd)
        self._write_fd = None

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
