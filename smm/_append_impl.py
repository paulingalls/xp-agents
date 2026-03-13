#!/usr/bin/env python3
"""SMM event builder, validator, and atomic appender.

Constructs a JSON event from CLI arguments, validates against the SMM schema,
and appends it atomically to events.jsonl using flock.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


def resolve_smm_dir() -> Path:
    """Derive the SMM directory from git-common-dir, matching init.sh logic."""
    try:
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    # Resolve to absolute path
    git_common_path = Path(git_common)
    if not git_common_path.is_absolute():
        git_common_path = git_common_path.resolve()

    project_id = hashlib.sha256(str(git_common_path).encode()).hexdigest()[:12]
    return Path.home() / ".claude" / "xp-agents" / project_id / "smm"


# ---------------------------------------------------------------------------
# Agent ID validation
# ---------------------------------------------------------------------------

_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_:\-]+$")


def _validate_smm_dir(smm_dir: Path) -> None:
    """Validate SMM directory exists, is owned by us, not world-writable."""
    if not smm_dir.exists():
        raise ValueError(f"SMM directory does not exist: {smm_dir}")
    st = smm_dir.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f"SMM directory not owned by current user: {smm_dir}")
    if st.st_mode & 0o002:
        raise ValueError(f"SMM directory is world-writable: {smm_dir}")


def _validate_agent_id(agent_id: str) -> None:
    """Reject agent IDs that don't match the allowlist pattern."""
    if not agent_id:
        raise ValueError("agent_id must not be empty")
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------

VALID_TYPES = sorted(
    [
        "customer_input",
        "status",
        "decision",
        "convention",
        "concern",
        "discovery",
        "question",
        "answer",
        "assumption",
        "pair_guidance",
        "session_end",
        "retrospective",
    ]
)

VALID_PRIORITIES = frozenset({"\U0001f534", "\U0001f7e1", "\U0001f7e2"})  # 🔴🟡🟢
VALID_SEVERITIES = frozenset({"high", "medium", "low"})


MAX_JSON_ARG_SIZE = 65536


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
        "id": str(uuid.uuid4()),
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
        case "status":
            if args.working_on is not None:
                event["working_on"] = parse_json_arg(args.working_on, "working-on")

        case "decision" | "convention":
            if args.topic is not None:
                event["topic"] = args.topic

        case "concern":
            if args.severity:
                event["severity"] = args.severity

        case "question":
            if args.priority is not None:
                event["priority"] = args.priority

        case "pair_guidance":
            if args.tool_name is not None:
                event["tool_name"] = args.tool_name

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
            if args.final_status_recorded is not None:
                event["final_status_recorded"] = args.final_status_recorded

        case "retrospective":
            if args.keep:
                event["keep"] = parse_json_arg(args.keep, "keep")
            if args.fix:
                event["fix"] = parse_json_arg(args.fix, "fix")
            if args.try_items:
                event["try"] = parse_json_arg(args.try_items, "try-items")

    return event


# ---------------------------------------------------------------------------
# Event validation (single source of truth for required-field checks)
# ---------------------------------------------------------------------------


def validate_event(event: dict) -> list[str]:
    """Validate event structure. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    # Universal required fields
    for field in ("id", "ts", "type", "agent_id", "content"):
        if field not in event:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(event[field], str):
            errors.append(f"Field '{field}' must be a string")

    if errors:
        return errors  # Can't validate further without basics

    event_type = event["type"]
    if event_type not in VALID_TYPES:
        errors.append(f"Invalid event type: {event_type}")
        return errors

    # Universal optional field types
    if "references" in event and not isinstance(event["references"], list):
        errors.append("Field 'references' must be an array")
    if "metadata" in event and not isinstance(event["metadata"], dict):
        errors.append("Field 'metadata' must be an object")
    if "schema_version" in event and not isinstance(event["schema_version"], int):
        errors.append("Field 'schema_version' must be an integer")

    # Type-specific validation
    match event_type:
        case "status":
            if "working_on" not in event:
                errors.append("Field 'working_on' is required for type 'status'")
            elif not isinstance(event["working_on"], list):
                errors.append("Field 'working_on' must be an array")

        case "decision" | "convention":
            if "topic" not in event:
                errors.append(f"Field 'topic' is required for type '{event_type}'")
            elif not isinstance(event["topic"], str):
                errors.append("Field 'topic' must be a string")

        case "concern":
            if "severity" in event and event["severity"] not in VALID_SEVERITIES:
                errors.append(
                    f"Invalid severity: {event['severity']} (must be high/medium/low)"
                )

        case "question":
            if "priority" not in event:
                errors.append("Field 'priority' is required for type 'question'")
            elif event["priority"] not in VALID_PRIORITIES:
                errors.append(
                    f"Invalid priority: {event['priority']}"
                    " (must be \U0001f534/\U0001f7e1/\U0001f7e2)"
                )

        case "pair_guidance":
            if "tool_name" not in event:
                errors.append("Field 'tool_name' is required for type 'pair_guidance'")
            elif not isinstance(event["tool_name"], str):
                errors.append("Field 'tool_name' must be a string")

        case "session_end":
            _check = {
                "duration_seconds": (int, float),
                "event_count": int,
                "unresolved_items": list,
                "working_on": list,
                "final_status_recorded": bool,
            }
            _labels = {
                (int, float): "a number",
                int: "an integer",
                list: "an array",
                bool: "a boolean",
            }
            for _f, _t in _check.items():
                if _f in event and not isinstance(event[_f], _t):
                    errors.append(f"Field '{_f}' must be {_labels[_t]}")

        case "retrospective":
            for field in ("keep", "fix", "try"):
                if field in event:
                    if not isinstance(event[field], list):
                        errors.append(f"Field '{field}' must be an array")
                    else:
                        for i, item in enumerate(event[field]):
                            if not isinstance(item, dict):
                                errors.append(f"Field '{field}[{i}]' must be an object")
                            elif "content" not in item:
                                errors.append(
                                    f"Field '{field}[{i}].content' is required"
                                )

    return errors


# ---------------------------------------------------------------------------
# Locked atomic append
# ---------------------------------------------------------------------------


class LockTimeoutError(Exception):
    """Raised when flock cannot be acquired within the timeout."""

    pass


def _on_alarm(signum: int, frame: object) -> None:
    raise LockTimeoutError("Could not acquire lock within 2 seconds")


def _safe_open_nofollow(path: Path, flags: int) -> int:
    """Open a file with O_NOFOLLOW to reject symlinks."""
    return os.open(str(path), flags | os.O_NOFOLLOW, 0o600)


def append_event(smm_dir: Path, event: dict) -> None:
    """Append event as a single JSON line to events.jsonl with flock.

    Raises LockTimeoutError if the lock cannot be acquired within 2 seconds.
    Raises OSError if lock or events file is a symlink.
    """
    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    line = json.dumps(event, ensure_ascii=False) + "\n"

    lock_fd = None
    raw_fd = None

    try:
        raw_fd = _safe_open_nofollow(lock_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None  # now owned by lock_fd

        # Use blocking flock with SIGALRM timeout (2 seconds)
        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        ev_fd = _safe_open_nofollow(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            with os.fdopen(ev_fd, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            os.close(ev_fd)
            raise

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for append operations."""
    parser = argparse.ArgumentParser(description="Append an event to the SMM event log")

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
    parser.add_argument("--tool-name", help="Tool name")

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
    parser.add_argument(
        "--final-status-recorded",
        type=lambda v: v.lower() == "true",
        help="Whether final status was recorded (session_end)",
    )

    # retrospective specific
    parser.add_argument("--keep", help="JSON array of keep items (retrospective)")
    parser.add_argument("--fix", help="JSON array of fix items (retrospective)")
    parser.add_argument("--try-items", help="JSON array of try items (retrospective)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate agent_id
    try:
        _validate_agent_id(args.agent)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve and validate SMM directory
    smm_dir = resolve_smm_dir()
    try:
        _validate_smm_dir(smm_dir)
    except ValueError as e:
        print(f"Error: {e}\nRun smm/init.sh first.", file=sys.stderr)
        sys.exit(1)

    # Build event
    event = build_event(args)

    # Validate
    errors = validate_event(event)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    # Append
    try:
        append_event(smm_dir, event)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
