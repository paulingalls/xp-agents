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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import identity
import spawn_command
import spawn_prompt
import teammate_stream_reader
import worktree

get_current_branch = identity.get_current_branch

# Re-exported because this module's own suites address them here: reading the
# stream moved to `teammate_stream_reader`, and the names those tests use are
# part of this module's established surface.
_DEFAULT_READ_TIMEOUT_S = teammate_stream_reader.DEFAULT_READ_TIMEOUT_S
_read_timeout = teammate_stream_reader.read_timeout
_is_result = teammate_stream_reader.is_result
parse_result_event = teammate_stream_reader.parse_result_event

_DECISION_BLOCK = "block"
# Markers that make a non-JSON line get its OWN dedicated wording ("Spawn
# failed: ...") ahead of the generic unrecognized-output tier below. The
# spawn's own refusal is the one signal we OWN rather than inherit from a
# tool's output conventions: it exits cleanly (no traceback), so without its
# token here it would fall through to the generic tier and lose its
# dedicated phrasing.
_ERROR_SIGNALS = (
    "Error:",
    "Error(",
    "fatal:",
    "Traceback",
    spawn_prompt.REFUSAL_PREFIX,
)

# Bounds on a diagnostic message: how many lines get quoted, and how much of
# each. Both are needed — the count alone does not stop ONE line from being a
# wall of text, and the reader yields any unterminated trailing fragment at
# EOF, so an abrupt mid-line EOF (the very failure this diagnostic serves) can
# hand back a read-chunk-sized line. The message keeps the shape; the
# stream-dump artifact keeps the verbatim text.
_DIAGNOSTIC_LINE_LIMIT = 10
_DIAGNOSTIC_LINE_CHARS = 200
# The recognised-signal tier gets a far LOOSER per-line bound, not none: the
# spawn's own refusal carries its remedy ~450 chars into a single line and must
# arrive whole (test_spawn_prompt_guard pins that contract). But a truncated
# JSON fragment whose text happens to carry "Error:" reaches this tier too —
# unbounded, that is a ~64KB dump into the lead's context.
_ERROR_LINE_CHARS = 2000


def _clip(line: str, limit: int) -> str:
    """Clip one quoted line to *limit* chars, naming the elision."""
    if len(line) <= limit:
        return line
    return f"{line[:limit]}... (+{len(line) - limit} chars truncated)"


def _bounded_join(items: list[str], limit: int = _DIAGNOSTIC_LINE_CHARS) -> str:
    """Join items with '; ', bounded in both line count and per-line length."""
    shown = [_clip(item, limit) for item in items[:_DIAGNOSTIC_LINE_LIMIT]]
    text = "; ".join(shown)
    remaining = len(items) - len(shown)
    if remaining > 0:
        text += f" (+{remaining} more)"
    return text


def extract_diagnostics(lines: list[str]) -> str:
    """Scan captured lines for block events, errors, and other diagnostics.

    Precedence: a hook block wins outright, then a recognised error signal
    (fatal:, Traceback, the spawn's own refusal, ...), then any OTHER non-JSON
    line is surfaced rather than silently dropped — captured lines that parse
    as neither a block nor a known error are still spawn-side evidence, and
    discarding them turns a real failure into an unexplained "No result
    event". Only once none of that is present does the generic fallback
    fire, and it reports the parsed-JSON count and the total captured-line
    count as two distinct figures rather than asserting the whole capture
    was stream-json.

    The spawn's OWN advisories (spawn_command.NOTICE_PREFIX) are excluded from
    the evidence tier: they say what the spawn resolved, not that anything went
    wrong, and the model one fires on every untiered spawn — so left in, they
    became the reported cause of every no-result failure and sent the lead
    chasing a --model problem that did not exist. They are still counted in the
    line totals, and the stream-dump artifact keeps them verbatim. The error
    tier runs FIRST, so a real refusal is never demoted by this.
    """
    if not lines:
        return "No output received from claude -p"

    blocks: list[str] = []
    non_json_lines: list[str] = []
    parsed_count = 0
    for line in lines:
        data = teammate_stream_reader.parse_stream_object(line)
        if data is None:
            non_json_lines.append(line)
            continue
        parsed_count += 1
        reason = data.get("reason", "")
        if data.get("decision") == _DECISION_BLOCK and reason:
            blocks.append(reason)

    if blocks:
        return "Blocked by hook: " + "; ".join(blocks)

    errors = [
        line for line in non_json_lines if any(sig in line for sig in _ERROR_SIGNALS)
    ]
    if errors:
        return "Spawn failed: " + _bounded_join(errors, _ERROR_LINE_CHARS)

    evidence = [
        line for line in non_json_lines if spawn_command.NOTICE_PREFIX not in line
    ]
    if evidence:
        return (
            f"Unrecognized output ({len(evidence)} of {len(lines)} line(s) "
            f"captured, {parsed_count} parsed as stream-json): "
            + _bounded_join(evidence)
        )

    return (
        f"No result event: {parsed_count} of {len(lines)} line(s) parsed as "
        "stream-json (no block detected)"
    )


# Marks every rendering of a terminal event that did NOT complete: the report
# file's first line, the completion event's content, and the summary line the
# lead reads. One token so none of the three can be made to look like the
# others' success shape by accident.
_FAILED = "FAILED"
_SUCCESS_SUBTYPE = "success"
_UNNAMED_FAILURE = "unspecified error"


def failure_reason(result: dict) -> str | None:
    """The terminal reason a result event carries, or None if it completed.

    Two independent signals, and EITHER alone is enough. `is_error` is the
    flag; `subtype` names which failure it was (error_during_execution,
    error_max_turns, ...) and is the half worth printing. Requiring both would
    reinstate the defect one signal at a time: the death that went unnoticed
    exited 0, and the exit status was the only thing anyone checked.

    A result carrying NEITHER signal is a success. Absence is not evidence
    here — a simpler harness emits a bare terminal event, and reading those as
    deaths would report every run it makes as failed.
    """
    subtype = result.get("subtype")
    named = isinstance(subtype, str) and subtype not in ("", _SUCCESS_SUBTYPE)
    if not named and not result.get("is_error"):
        return None
    return subtype if named else _UNNAMED_FAILURE


def write_report(
    smm_dir: Path, teammate_id: str, result_text: str, *, failure: str | None = None
) -> Path:
    """Write teammate report file. Returns the file path.

    A failed run's report holds nothing but the error string, which on its own
    reads like a note the teammate chose to leave. The header says otherwise,
    on the first line, before the text it belongs to.
    """
    path = worktree.teammate_report_path(smm_dir, teammate_id)
    if failure is not None:
        result_text = f"TEAMMATE {_FAILED} ({failure})\n---\n{result_text}"
    path.write_text(result_text)
    return path


def record_completion(
    smm_dir: Path,
    teammate_id: str,
    result: dict,
    *,
    failure: str | None = None,
) -> None:
    """Append a completion event with cost/duration metadata.

    A death records its cost and turns like any other run — the money was
    spent and the turns were taken, and dropping them would hide an expensive
    failure from every cost and velocity reading. Only the CLAIM changes:
    "completed" is not true of a run that died, and a reader that aggregates
    gets a metadata flag rather than having to parse the prose.
    """
    cost = result.get("total_cost_usd", 0.0)
    turns = result.get("num_turns", 0)
    duration_ms = result.get("duration_ms", 0)
    minutes = duration_ms // 60000
    seconds = (duration_ms % 60000) // 1000
    outcome = "completed" if failure is None else f"{_FAILED} ({failure})"
    content = f"Teammate {outcome}: ${cost:.2f}, {turns} turns, {minutes}m {seconds}s"
    metadata = {
        "cost_usd": cost,
        "turns": turns,
        "duration_ms": duration_ms,
    }
    if failure is not None:
        metadata["failed"] = True
        metadata["failure_reason"] = failure
    event = _common.make_event(
        _common.STATUS,
        teammate_id,
        content,
        working_on=[],
        metadata=metadata,
    )
    _common.append_safe(smm_dir, event)


def format_summary(
    report_path: Path, branch_name: str, cost: float, *, failure: str | None = None
) -> str:
    """One-line summary for the lead's Bash task output.

    The failure shape leads with the verdict rather than the report path: the
    lead skims this line, and a death that opened with `Report: ...` is
    precisely how one went unnoticed while acceptance ran against its branch.
    """
    tail = f"Report: {report_path} | Branch: {branch_name} | Cost: ${cost:.2f}"
    if failure is None:
        return tail
    return f"TEAMMATE {_FAILED} ({failure}) — the run did not complete. {tail}"


# Retention cap for the stream-dump artifact. Split head/tail rather than
# tail-only: a refusal or WARN printed early and then buried under noise is
# exactly the case the artifact exists to preserve, and tail-only retention
# would elide it.
_STREAM_DUMP_MAX_LINES = 500


def _trim_for_dump(lines: list[str]) -> tuple[list[str], int]:
    """Keep head + tail of *lines* within _STREAM_DUMP_MAX_LINES. Returns
    (retained_lines_with_elision_marker, elided_count)."""
    if len(lines) <= _STREAM_DUMP_MAX_LINES:
        return list(lines), 0
    half = _STREAM_DUMP_MAX_LINES // 2
    head = lines[:half]
    tail = lines[-half:]
    elided = len(lines) - len(head) - len(tail)
    return [*head, f"... ({elided} line(s) elided) ...", *tail], elided


def _compose_stream_dump(
    lines: list[str],
    *,
    mode: str,
    timeout: float | None,
    parsed_count: int,
    total_count: int,
) -> str:
    """Compose the verbatim stream-dump artifact text: header + retained lines.

    Composition (header wording, retention trim) is the filter's knowledge;
    the writer it hands the finished string to (worktree.
    write_teammate_stream_dump) knows only the path and the write.
    """
    retained, elided = _trim_for_dump(lines)
    header = [
        f"mode: {mode}",
        f"timeout_s: {timeout if timeout is not None else 'n/a'}",
        f"parsed_stream_json_lines: {parsed_count}",
        f"total_captured_lines: {total_count}",
        f"elided_lines: {elided}",
    ]
    return "\n".join(header) + "\n---\n" + "\n".join(retained) + "\n"


def process_stream(smm_dir: Path, teammate_id: str) -> None:
    """Read stdin stream-json with progress timeout, capture result, write report."""
    timeout = _read_timeout()
    fd = sys.stdin.fileno()
    lines, result, timed_out = teammate_stream_reader.consume_stream(fd, timeout)

    if result is None:
        parsed_count = sum(1 for _ in teammate_stream_reader.iter_json_objects(lines))
        mode = "timeout" if timed_out else "eof"
        dump_text = _compose_stream_dump(
            lines,
            mode=mode,
            timeout=timeout if timed_out else None,
            parsed_count=parsed_count,
            total_count=len(lines),
        )
        dump_path: Path | None = None
        dump_error: OSError | None = None
        try:
            dump_path = worktree.write_teammate_stream_dump(
                smm_dir, teammate_id, dump_text
            )
        except OSError as exc:
            dump_error = exc

        diag = extract_diagnostics(lines)
        if timed_out:
            diag = f"Timeout after {timeout}s with no teammate output. {diag}"
        else:
            diag = f"Stream closed (EOF) with no result event. {diag}"
        if dump_path is not None:
            diag += f" Captured output saved to {dump_path}"
        elif dump_error is not None:
            diag += f" (failed to save captured output: {dump_error})"
        print(diag, file=sys.stderr)
        sys.exit(1)

    # A terminal event is not the same claim as a successful one. This branch
    # took the success path for ANY result event, so a teammate killed by an
    # API drop mid-edit — exit 0, `is_error` true, a report holding only the
    # error string — was handed to the lead as `Report: … | Cost: $8.86`.
    failure = failure_reason(result)
    cost = result.get("total_cost_usd", 0.0)
    result_text = result.get("result", "")

    report_path = write_report(smm_dir, teammate_id, result_text, failure=failure)
    record_completion(smm_dir, teammate_id, result, failure=failure)
    # Cleared either way. The process is gone and this filter watched it go, so
    # the entry can only mislead from here: it pins the dead teammate's files
    # against every other agent, and its heartbeat is FRESH at the moment of
    # death, so the liveness leg would read it as working for hours.
    coordination.clear_coordination_agent(smm_dir, teammate_id)

    branch = get_current_branch(str(smm_dir))
    summary = format_summary(report_path, branch or teammate_id, cost, failure=failure)
    if failure is None:
        print(summary)
        return
    # Non-zero, on the same channel as the no-result path just above. Exiting 0
    # is what hid the earlier death: the spawn saw a clean exit and the lead
    # ran acceptance against a half-finished branch.
    print(summary, file=sys.stderr)
    sys.exit(1)


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
