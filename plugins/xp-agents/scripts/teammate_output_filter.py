#!/usr/bin/env python3
"""Filter stream-json output from a CLI teammate session.

Reads stream-json lines from stdin (piped from claude -p), captures
the type:result event, writes a report file, and appends a cost/duration
event to the SMM.

Usage:
    claude -p ... --output-format stream-json --verbose \
      | python3 teammate_output_filter.py \
        --smm-dir /path/to/smm \
        --teammate-id worktree-story-001
"""

import argparse
import json
import os
import select
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import identity
import teammate_runner
import worktree

get_current_branch = identity.get_current_branch

_DECISION_BLOCK = "block"
_STREAM_JSON_RESULT_TYPE = "result"
_ERROR_SIGNALS = ("Error:", "Error(", "fatal:", "Traceback")

# No-progress deadline. Primary liveness is owned by spawn_teammate.py's
# watchdog (teammate_runner._WATCHDOG_TIMEOUT_S): when the child `claude -p`
# goes silent the watchdog kills it, the stream EOFs, and the no-result path
# below fires. A deadline here SHORTER than the watchdog would preempt it and
# kill teammates during legitimately silent tool calls (nested reviews,
# acceptance runs) — the stream is silent to the parent stdout even though the
# teammate is working. So the default deadline is set LONGER than the watchdog
# window (+ kill grace + margin): it never preempts the watchdog and never
# fires during healthy-but-silent work, yet still provides a SECOND, independent
# backstop the watchdog cannot — a spawn-side tee-loop wedge (e.g. blocked in a
# log flush) where the stream neither advances nor EOFs, which would otherwise
# hang this filter forever. Set XP_TEAMMATE_FILTER_TIMEOUT to override; "0" (or
# any value <= 0) disables the deadline entirely (block until EOF). Tests also
# use the override to force the timeout path quickly.
_TIMEOUT_ENV_VAR = "XP_TEAMMATE_FILTER_TIMEOUT"
_BACKSTOP_MARGIN_S = 300
_DEFAULT_READ_TIMEOUT_S = (
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


def _read_timeout() -> float | None:
    """No-progress deadline in seconds, or None for no deadline.

    Env unset/empty → the watchdog-exceeding backstop default
    (_DEFAULT_READ_TIMEOUT_S). An explicit XP_TEAMMATE_FILTER_TIMEOUT
    overrides; a value <= 0 disables the deadline (None), so a stray "0"
    means "block until EOF" rather than an instant-timeout that would abort
    a healthy run.

    Read each call so tests can override without re-importing the module.
    """
    raw = os.environ.get(_TIMEOUT_ENV_VAR)
    if not raw:
        return _DEFAULT_READ_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        # A malformed override must not crash the filter (the teammate's sole
        # stdout reader) — that would re-deadlock the very run this guards.
        sys.stderr.write(
            f"WARN: invalid {_TIMEOUT_ENV_VAR}={raw!r}; using default backstop\n"
        )
        return _DEFAULT_READ_TIMEOUT_S
    return value if value > 0 else None


def _iter_lines_with_timeout(fd: int, timeout: float | None) -> Iterator[str]:
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


def _iter_json_objects(lines: list[str]) -> Iterator[dict]:
    """Yield parsed JSON objects from stream-json lines, skipping malformed."""
    for line in lines:
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _is_result(data: dict) -> bool:
    """Stream-json terminal-event predicate. Single source of truth.

    Used by parse_result_event (list-based, edge-case unit-tested) AND by
    _consume_stream (fd-based, integration-tested). Keeps both detection
    paths in sync.
    """
    return data.get("type") == _STREAM_JSON_RESULT_TYPE


def parse_result_event(lines: list[str]) -> dict | None:
    """Find the type:result event in stream-json lines."""
    for data in _iter_json_objects(lines):
        if _is_result(data):
            return data
    return None


def extract_diagnostics(lines: list[str]) -> str:
    """Scan stream-json lines for block events, errors, and other diagnostics.

    Returns a human-readable summary for debugging spawn failures.
    """
    if not lines:
        return "No output received from claude -p"

    blocks: list[str] = []
    for data in _iter_json_objects(lines):
        reason = data.get("reason", "")
        if data.get("decision") == _DECISION_BLOCK and reason:
            blocks.append(reason)

    if blocks:
        return "Blocked by hook: " + "; ".join(blocks)

    errors = [
        line
        for line in lines
        if not line.startswith("{") and any(sig in line for sig in _ERROR_SIGNALS)
    ]
    if errors:
        return "Spawn failed: " + "; ".join(errors)

    return f"No result event in {len(lines)} stream-json lines (no block detected)"


def write_report(smm_dir: Path, teammate_id: str, result_text: str) -> Path:
    """Write teammate report file. Returns the file path."""
    path = worktree.teammate_report_path(smm_dir, teammate_id)
    path.write_text(result_text)
    return path


def record_completion(
    smm_dir: Path,
    teammate_id: str,
    result: dict,
) -> None:
    """Append a completion event with cost/duration metadata."""
    cost = result.get("total_cost_usd", 0.0)
    turns = result.get("num_turns", 0)
    duration_ms = result.get("duration_ms", 0)
    minutes = duration_ms // 60000
    seconds = (duration_ms % 60000) // 1000
    content = f"Teammate completed: ${cost:.2f}, {turns} turns, {minutes}m {seconds}s"
    event = _common.make_event(
        _common.STATUS,
        teammate_id,
        content,
        working_on=[],
        metadata={
            "cost_usd": cost,
            "turns": turns,
            "duration_ms": duration_ms,
        },
    )
    _common.append_safe(smm_dir, event)


def format_summary(report_path: Path, branch_name: str, cost: float) -> str:
    """One-line summary for the lead's Bash task output."""
    return f"Report: {report_path} | Branch: {branch_name} | Cost: ${cost:.2f}"


def _consume_stream(
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
        for line in _iter_lines_with_timeout(fd, timeout):
            lines.append(line)
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _is_result(data):
                result = data
                # Drain any trailing lines briefly; ignore another timeout here.
                try:
                    for extra in _iter_lines_with_timeout(
                        fd, _POST_RESULT_DRAIN_TIMEOUT
                    ):
                        lines.append(extra)
                except TimeoutError:
                    pass
                break
    except TimeoutError:
        timed_out = True

    return lines, result, timed_out


def process_stream(smm_dir: Path, teammate_id: str) -> None:
    """Read stdin stream-json with progress timeout, capture result, write report."""
    timeout = _read_timeout()
    fd = sys.stdin.fileno()
    lines, result, timed_out = _consume_stream(fd, timeout)

    if result is None:
        diag = extract_diagnostics(lines)
        if timed_out:
            diag = f"Timeout after {timeout}s with no teammate output. {diag}"
        print(diag, file=sys.stderr)
        sys.exit(1)

    cost = result.get("total_cost_usd", 0.0)
    result_text = result.get("result", "")

    report_path = write_report(smm_dir, teammate_id, result_text)
    record_completion(smm_dir, teammate_id, result)
    coordination.clear_coordination_agent(smm_dir, teammate_id)

    branch = get_current_branch(str(smm_dir))
    summary = format_summary(report_path, branch or teammate_id, cost)
    print(summary)


def main(
    smm_dir: Path | None = None,
    teammate_id: str | None = None,
) -> None:
    """Entry point — use provided values, else parse CLI args."""
    if smm_dir is not None and teammate_id is not None:
        process_stream(smm_dir, teammate_id)
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--teammate-id", required=True)
    args = parser.parse_args()
    process_stream(Path(args.smm_dir), args.teammate_id)


if __name__ == "__main__":
    main()
