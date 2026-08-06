#!/usr/bin/env python3
"""Reading a CLI teammate's stream-json: the deadline, the fd, the parsing.

Everything here answers one question — what came out of `claude -p`, and did a
terminal event arrive? It knows nothing about the SMM, the report file or the
teammate's identity; `teammate_output_filter` owns what the answer MEANS.

Extracted from that module, which sat at its size ceiling. The split is along
the seam the two halves already had: this one is pure input handling and is
exercised through a real OS pipe, while the half left behind writes files and
appends events.
"""

import json
import os
import select
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import teammate_runner

STREAM_JSON_RESULT_TYPE = "result"

# No-progress deadline. Primary liveness is owned by spawn_teammate.py's
# watchdog (teammate_runner._WATCHDOG_TIMEOUT_S): when the child `claude -p`
# goes silent the watchdog kills it, the stream EOFs, and the no-result path
# fires. A deadline here SHORTER than the watchdog would preempt it and
# kill teammates during legitimately silent tool calls (nested reviews,
# acceptance runs) — the stream is silent to the parent stdout even though the
# teammate is working. So the default deadline is set LONGER than the watchdog
# window (+ kill grace + margin): it never preempts the watchdog and never
# fires during healthy-but-silent work, yet still provides a SECOND, independent
# backstop the watchdog cannot — a spawn-side tee-loop wedge (e.g. blocked in a
# log flush) where the stream neither advances nor EOFs, which would otherwise
# hang the filter forever. Set XP_TEAMMATE_FILTER_TIMEOUT to override; "0" (or
# any value <= 0) disables the deadline entirely (block until EOF). Tests also
# use the override to force the timeout path quickly.
TIMEOUT_ENV_VAR = "XP_TEAMMATE_FILTER_TIMEOUT"
_BACKSTOP_MARGIN_S = 300
DEFAULT_READ_TIMEOUT_S = (
    teammate_runner._WATCHDOG_TIMEOUT_S
    + teammate_runner._WATCHDOG_KILL_GRACE_S
    + _BACKSTOP_MARGIN_S
)
# Brief drain after the result event so any final lines (warnings, hook
# diagnostics) make it into the lines list before EOF. 0.1s suits the
# common case where claude -p closes stdout immediately after `result`;
# on a contended host a slower trailing line could be lost, but stream-
# json treats `result` as terminal so the diagnostic value of any tail
# is low enough that env-overriding this would be overkill.
_POST_RESULT_DRAIN_TIMEOUT = 0.1
_READ_CHUNK_BYTES = 65536


def read_timeout() -> float | None:
    """No-progress deadline in seconds, or None for no deadline.

    Env unset/empty → the watchdog-exceeding backstop default
    (DEFAULT_READ_TIMEOUT_S). An explicit XP_TEAMMATE_FILTER_TIMEOUT
    overrides; a value <= 0 disables the deadline (None), so a stray "0"
    means "block until EOF" rather than an instant-timeout that would abort
    a healthy run.

    Read each call so tests can override without re-importing the module.
    """
    raw = os.environ.get(TIMEOUT_ENV_VAR)
    if not raw:
        return DEFAULT_READ_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        # A malformed override must not crash the filter (the teammate's sole
        # stdout reader) — that would re-deadlock the very run this guards.
        sys.stderr.write(
            f"WARN: invalid {TIMEOUT_ENV_VAR}={raw!r}; using default backstop\n"
        )
        return DEFAULT_READ_TIMEOUT_S
    return value if value > 0 else None


def iter_lines_with_timeout(fd: int, timeout: float | None) -> Iterator[str]:
    """Yield decoded lines from fd; raise TimeoutError on no progress.

    When *timeout* is None there is no deadline — select blocks until the fd is
    readable or EOF (liveness is the spawn watchdog's job). A float *timeout*
    raises TimeoutError after that many seconds of no activity (opt-in backstop).

    Drives os.read directly (NOT sys.stdin.readline) because select on a
    buffered TextIOWrapper deadlocks: bytes can sit in Python's read-ahead
    buffer with the OS pipe empty, so select reports "not ready" and the
    caller hangs.
    """
    buf = b""
    while True:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            raise TimeoutError(f"no stdin activity for {timeout}s")
        chunk = os.read(fd, _READ_CHUNK_BYTES)
        if not chunk:
            if buf:
                yield buf.decode("utf-8", errors="replace")
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")


def parse_stream_object(line: str) -> dict | None:
    """Parse one captured line as a stream-json event, or None if it isn't one.

    Single definition of "parsed as stream-json", shared by the fd-side reader
    (consume_stream), parse_result_event and extract_diagnostics, so the
    diagnostic's counts cannot drift from what the reader actually accepted.

    Non-object JSON (a bare number, string, null, array) is NOT an event: the
    stream is merged with the spawn's stderr (2>&1), so such a line is
    spawn-side text that happens to be JSON-parseable. Returning it would hand
    a non-dict to `.get()` and kill the filter — the teammate's sole stdout
    reader — losing the whole capture on the exact path meant to preserve it.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def iter_json_objects(lines: list[str]) -> Iterator[dict]:
    """Yield parsed JSON objects from stream-json lines, skipping malformed."""
    for line in lines:
        data = parse_stream_object(line)
        if data is not None:
            yield data


def is_result(data: dict) -> bool:
    """Stream-json terminal-event predicate. Single source of truth.

    Used by parse_result_event (list-based, edge-case unit-tested) AND by
    consume_stream (fd-based, integration-tested). Keeps both detection
    paths in sync.
    """
    return data.get("type") == STREAM_JSON_RESULT_TYPE


def parse_result_event(lines: list[str]) -> dict | None:
    """Find the type:result event in stream-json lines."""
    for data in iter_json_objects(lines):
        if is_result(data):
            return data
    return None


def consume_stream(
    fd: int, timeout: float | None
) -> tuple[list[str], dict | None, bool]:
    """Read until a result event arrives, EOF, or no-progress timeout.

    Returns (lines_seen, result_event_or_None, timed_out_flag).
    On result-event hit, drains briefly so trailing lines are captured
    without risking another full-timeout wait.
    """
    lines: list[str] = []
    result: dict | None = None
    timed_out = False

    try:
        for line in iter_lines_with_timeout(fd, timeout):
            lines.append(line)
            data = parse_stream_object(line)
            if data is None:
                continue
            if is_result(data):
                result = data
                # Drain any trailing lines briefly; ignore another timeout here.
                try:
                    for extra in iter_lines_with_timeout(
                        fd, _POST_RESULT_DRAIN_TIMEOUT
                    ):
                        lines.append(extra)
                except TimeoutError:
                    pass
                break
    except TimeoutError:
        timed_out = True

    return lines, result, timed_out
