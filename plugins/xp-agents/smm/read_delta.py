#!/usr/bin/env python3
"""SMM Delta Reader: per-agent watermark + tiered filtering.

Reads new events since an agent's last read position, with tiered
filtering based on tool context. Watermark only advances on full reads.
"""

import argparse
import json
import sys
from pathlib import Path

from _append_impl import (
    PRIORITY_BLOCKING,
    LockTimeoutError,
    _validate_agent_id,
    _validate_smm_dir,
    resolve_smm_dir,
    write_watermark,
)
from _append_impl import (
    read_with_lock as _read_with_lock,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIER_FULL = "full"
TIER_BLOCKING = "blocking"
TIER_RED_ONLY = "red-only"
VALID_TIERS = frozenset({TIER_FULL, TIER_BLOCKING, TIER_RED_ONLY})


def read_watermark(smm_dir: Path, agent_id: str) -> int:
    """Read watermark for agent. Returns 0 if missing or corrupt.

    Rejects symlinks at the watermark path (O_NOFOLLOW).
    """
    import os as _os

    _validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"
    try:
        fd = _os.open(str(wm_file), _os.O_RDONLY | _os.O_NOFOLLOW)
        try:
            content = _os.read(fd, 64).decode().strip()
        finally:
            _os.close(fd)
        value = int(content)
        return max(0, value)
    except (FileNotFoundError, ValueError, OSError):
        return 0


# ---------------------------------------------------------------------------
# Event reading
# ---------------------------------------------------------------------------


def read_events_from(smm_dir: Path, start_line: int) -> tuple[list[dict], int]:
    """Read events from line N under shared flock. Returns (events, total_lines)."""
    raw = _read_with_lock(smm_dir / "events.jsonl")
    if not raw:
        return [], 0

    lines = raw.splitlines()
    total = len(lines)

    events: list[dict] = []
    for line in lines[start_line:]:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue

    return events, total


# ---------------------------------------------------------------------------
# Tiered filtering
# ---------------------------------------------------------------------------


def filter_by_tier(events: list[dict], tier: str) -> list[dict]:
    """Filter events by tier using match/case."""
    match tier:
        case "full":
            return events
        case "blocking":
            return [
                e
                for e in events
                if (
                    e.get("type") == "question"
                    and e.get("priority") == PRIORITY_BLOCKING
                )
            ]
        case "red-only":
            return [
                e
                for e in events
                if (
                    e.get("type") == "question"
                    and e.get("priority") == PRIORITY_BLOCKING
                )
            ]
        case _:
            return events


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_delta(events: list[dict]) -> str:
    """Format events as compact text for additionalContext injection."""
    if not events:
        return ""

    lines = [f'<smm-delta count="{len(events)}">']

    for e in events:
        eid = e.get("id", "")[:8]
        agent = e.get("agent_id", "")
        content = e.get("content", "")
        etype = e.get("type", "")

        match etype:
            case "goal":
                lines.append(f"GOAL [{eid}]: {content}")
            case "debt":
                files = ", ".join(e.get("files", []))
                lines.append(f"DEBT [{eid}] (files: {files}): {content}")
            case "customer_intent":
                intent_status = e.get("intent_status", "")
                lines.append(f"INTENT [{eid}] ({intent_status}): {content}")
            case "decision":
                topic = e.get("topic", "")
                draft = " (draft)" if e.get("metadata", {}).get("draft") else ""
                lines.append(f"DECISION{draft} [{eid}] ({topic}): {content}")
            case "convention":
                topic = e.get("topic", "")
                lines.append(f"CONVENTION [{eid}] ({topic}): {content}")
            case "question":
                priority = e.get("priority", "")
                lines.append(f"QUESTION {priority} [{eid}]: {content}")
            case "answer":
                refs = ", ".join(r[:8] for r in e.get("references", []))
                lines.append(f"ANSWER [{eid}] (re: {refs}): {content}")
            case "concern":
                lines.append(f"CONCERN [{eid}]: {content}")
            case "discovery":
                lines.append(f"DISCOVERY [{eid}]: {content}")
            case "assumption":
                lines.append(f"ASSUMPTION [{eid}]: {content}")
            case "status":
                files = ", ".join(e.get("working_on", []))
                lines.append(f"STATUS [{agent}]: {content} (working on: {files})")
            case "customer_input":
                lines.append(f"CUSTOMER: {content}")
            case _:
                lines.append(f"{etype.upper()} [{eid}]: {content}")

    lines.append("</smm-delta>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def read_delta(
    smm_dir: Path,
    agent_id: str,
    tier: str = TIER_FULL,
    update_watermark: bool = True,
) -> list[dict]:
    """Read new events for agent, filtered by tier. Returns event list."""
    try:
        _validate_smm_dir(smm_dir)
    except ValueError:
        return []

    watermark = read_watermark(smm_dir, agent_id)
    events, total_lines = read_events_from(smm_dir, watermark)
    filtered = filter_by_tier(events, tier)

    # Only advance watermark on full reads
    if update_watermark and tier == TIER_FULL and total_lines > watermark:
        write_watermark(smm_dir, agent_id, total_lines)

    return filtered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read SMM delta for an agent with tiered filtering"
    )
    parser.add_argument(
        "--agent-id",
        default="main",
        help="Agent ID (default: main)",
    )
    parser.add_argument(
        "--tier",
        default=TIER_FULL,
        choices=sorted(VALID_TIERS),
        help="Filter tier (default: full)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON array",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="Don't update watermark after read",
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        help="Override SMM directory (default: auto-detect from git)",
    )
    args = parser.parse_args()

    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()

    try:
        _validate_smm_dir(smm_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        events = read_delta(
            smm_dir,
            agent_id=args.agent_id,
            tier=args.tier,
            update_watermark=not args.no_update,
        )
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        print(json.dumps(events, ensure_ascii=False, indent=2))
    else:
        output = format_delta(events)
        if output:
            print(output)


if __name__ == "__main__":
    main()
