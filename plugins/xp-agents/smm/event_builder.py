#!/usr/bin/env python3
"""Event builder: CLI argument parsing and event dict construction.

Converts argparse.Namespace into event dicts. No I/O, no validation
(that's event_schema.validate_event's job).

Extracted from _append_impl.py for module size management.
"""

import argparse
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from event_schema import CONTENT_BUDGETS, MAX_JSON_ARG_SIZE, VALID_TYPES


def generate_id() -> str:
    """12-char hex ID for events and SMM entries."""
    return secrets.token_hex(6)


def parse_json_arg(value: str, name: str) -> list | dict:
    """Parse a JSON string argument, exit on failure or oversized input."""
    if len(value) > MAX_JSON_ARG_SIZE:
        print(
            f"Error: --{name} value too large "
            f"({len(value)} > {MAX_JSON_ARG_SIZE} bytes)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON for --{name}: {e}", file=sys.stderr)
        sys.exit(1)


def build_event(args: argparse.Namespace) -> dict:
    """Construct an event dict from parsed CLI arguments.

    Does not validate required fields — that's validate_event's job.
    """
    event: dict = {
        "id": generate_id(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": args.type,
        "agent_id": args.agent,
        "content": args.content,
        "schema_version": 1,
    }

    # Universal optional fields
    if args.references:
        event["references"] = parse_json_arg(args.references, "references")
    if args.metadata:
        event["metadata"] = parse_json_arg(args.metadata, "metadata")

    # Type-specific fields — just map args to event fields, no validation
    match args.type:
        case "debt":
            if args.files is not None:
                event["files"] = parse_json_arg(args.files, "files")

        case "customer_intent":
            if args.intent_status is not None:
                event["intent_status"] = args.intent_status

        case "status":
            if args.working_on is not None:
                event["working_on"] = parse_json_arg(args.working_on, "working-on")
            else:
                event["working_on"] = []

        case "decision" | "convention":
            if args.topic is not None:
                event["topic"] = args.topic

        case "concern":
            if args.severity:
                event["severity"] = args.severity

        case "question":
            if args.priority is not None:
                event["priority"] = args.priority

        case "session_end":
            if args.duration_seconds is not None:
                event["duration_seconds"] = args.duration_seconds
            if args.event_count is not None:
                event["event_count"] = args.event_count
            if args.unresolved_items:
                event["unresolved_items"] = parse_json_arg(
                    args.unresolved_items, "unresolved-items"
                )
            if args.working_on:
                event["working_on"] = parse_json_arg(args.working_on, "working-on")
        case "retrospective":
            if args.keep:
                event["keep"] = parse_json_arg(args.keep, "keep")
            if args.fix:
                event["fix"] = parse_json_arg(args.fix, "fix")
            if args.try_items:
                event["try"] = parse_json_arg(args.try_items, "try-items")

    return event


def _format_budget_epilog() -> str:
    """Generate CLI help epilog with content budgets and usage examples."""
    entries = [
        f"{t}={b}" if b is not None else f"{t}=uncapped"
        for t, b in CONTENT_BUDGETS.items()
    ]
    lines = ["Content budgets (chars):"]
    for i in range(0, len(entries), 4):
        lines.append("  " + "  ".join(entries[i : i + 4]))
    lines.append("Over-budget events are rejected with an actionable error.")
    lines.append("")
    lines.append("Examples:")
    lines.append(
        "  append.sh --smm-dir DIR --type status --agent main"
        ' --content "Starting refactor" --working-on \'["src/auth.py"]\''
    )
    lines.append(
        "  append.sh --smm-dir DIR --type decision --agent main"
        ' --content "Use typed errors" --topic error-handling'
    )
    lines.append(
        "  append.sh --smm-dir DIR --type concern --agent main"
        ' --content "Missing validation" --severity medium'
    )
    lines.append(
        "  append.sh --smm-dir DIR --type debt --agent main"
        ' --content "Legacy code" --files \'["src/legacy.ts"]\''
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for append operations."""
    parser = argparse.ArgumentParser(
        description="Append an event to the SMM event log",
        epilog=_format_budget_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Optional SMM directory override (avoids CLAUDE_PLUGIN_DATA env var issues)
    parser.add_argument(
        "--smm-dir", type=Path, help="SMM directory (auto-resolved if omitted)"
    )

    # Universal required
    parser.add_argument("--type", required=True, choices=VALID_TYPES, help="Event type")
    parser.add_argument("--agent", required=True, help="Agent ID")
    parser.add_argument("--content", required=True, help="Event content")

    # Universal optional
    parser.add_argument("--references", help="JSON array of referenced event IDs")
    parser.add_argument("--metadata", help="JSON object of metadata")

    # Type-specific
    parser.add_argument(
        "--working-on",
        help="JSON array of file paths",
    )
    parser.add_argument("--topic", help="Topic string")
    parser.add_argument("--priority", help="Priority emoji")
    parser.add_argument(
        "--severity",
        choices=["high", "medium", "low"],
    )

    # debt/concern specific
    parser.add_argument("--files", help="JSON array of file paths (debt, concern)")

    # customer_intent specific
    parser.add_argument(
        "--intent-status",
        choices=["open", "delivered", "superseded"],
        help="Intent status (customer_intent)",
    )

    # session_end specific
    parser.add_argument(
        "--duration-seconds",
        type=float,
        help="Session duration",
    )
    parser.add_argument(
        "--event-count",
        type=int,
        help="Event count",
    )
    parser.add_argument(
        "--unresolved-items",
        help="JSON array of unresolved IDs",
    )
    # retrospective specific
    parser.add_argument("--keep", help="JSON array of keep items (retrospective)")
    parser.add_argument("--fix", help="JSON array of fix items (retrospective)")
    parser.add_argument("--try-items", help="JSON array of try items (retrospective)")

    return parser
