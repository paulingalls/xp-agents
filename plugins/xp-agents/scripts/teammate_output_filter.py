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
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import identity
import worktree

get_current_branch = identity.get_current_branch

_DECISION_BLOCK = "block"


def _iter_json_objects(lines: list[str]) -> Iterator[dict]:
    """Yield parsed JSON objects from stream-json lines, skipping malformed."""
    for line in lines:
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def parse_result_event(lines: list[str]) -> dict | None:
    """Find the type:result event in stream-json lines."""
    for data in _iter_json_objects(lines):
        if data.get("type") == "result":
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

    _ERROR_SIGNALS = ("Error:", "Error(", "fatal:", "Traceback")
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


def process_stream(smm_dir: Path, teammate_id: str) -> None:
    """Read stdin stream-json, capture result, write report."""
    lines = [line.rstrip("\n") for line in sys.stdin]
    result = parse_result_event(lines)

    if result is None:
        diag = extract_diagnostics(lines)
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
    """Entry point — parse args or use provided values."""
    if smm_dir is None or teammate_id is None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--smm-dir", required=True)
        parser.add_argument("--teammate-id", required=True)
        args = parser.parse_args()
        smm_dir = Path(args.smm_dir)
        teammate_id = args.teammate_id

    assert smm_dir is not None and teammate_id is not None
    process_stream(smm_dir, teammate_id)


if __name__ == "__main__":
    main()
