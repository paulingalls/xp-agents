#!/usr/bin/env python3
"""SMM Delta Reader: per-agent watermark + tiered filtering.

Reads new events since an agent's last read position, with tiered
filtering based on tool context. Watermark only advances on full reads.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIER_FULL = "full"
TIER_BLOCKING = "blocking"
TIER_RED_ONLY = "red-only"
VALID_TIERS = frozenset({TIER_FULL, TIER_BLOCKING, TIER_RED_ONLY})

PRIORITY_RED = "\U0001f534"


# ---------------------------------------------------------------------------
# SMM path resolution (duplicated for self-containment)
# ---------------------------------------------------------------------------


def resolve_smm_dir() -> Path:
    """Derive the SMM directory from git-common-dir."""
    try:
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    git_common_path = Path(git_common)
    if not git_common_path.is_absolute():
        git_common_path = git_common_path.resolve()

    project_id = hashlib.sha256(str(git_common_path).encode()).hexdigest()[:12]
    return Path.home() / ".claude" / "xp-agents" / project_id / "smm"


# ---------------------------------------------------------------------------
# Locking helpers (duplicated from _append_impl.py per design decision)
# ---------------------------------------------------------------------------


class LockTimeoutError(Exception):
    """Raised when flock cannot be acquired within the timeout."""

    pass


def _on_alarm(signum: int, frame: object) -> None:
    raise LockTimeoutError("Could not acquire lock within 2 seconds")


# ---------------------------------------------------------------------------
# Watermark management
# ---------------------------------------------------------------------------


_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_:\-]+$")


def _validate_agent_id(agent_id: str) -> None:
    """Reject agent IDs that don't match the allowlist pattern."""
    if not agent_id:
        raise ValueError("agent_id must not be empty")
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


def read_watermark(smm_dir: Path, agent_id: str) -> int:
    """Read watermark for agent. Returns 0 if missing or corrupt."""
    _validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"
    try:
        content = wm_file.read_text().strip()
        value = int(content)
        return max(0, value)
    except (FileNotFoundError, ValueError):
        return 0


def write_watermark(smm_dir: Path, agent_id: str, line_count: int) -> None:
    """Atomic write of watermark via temp + rename."""
    _validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"

    fd, tmp = tempfile.mkstemp(dir=smm_dir, prefix=f".wm-{agent_id}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(line_count))
        os.rename(tmp, wm_file)
        os.chmod(wm_file, 0o600)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# Locking helper
# ---------------------------------------------------------------------------


def _read_with_lock(path: Path) -> str:
    """Read file contents under shared flock with 2-second timeout.

    Raises LockTimeoutError if the lock cannot be acquired.
    Raises OSError if the lock file is a symlink.
    """
    lock_path = path.parent / "events.lock"
    lock_fd = None
    raw_fd = None

    try:
        raw_fd = os.open(
            str(lock_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


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
                if (e.get("type") == "question" and e.get("priority") == PRIORITY_RED)
                or e.get("type") == "pair_guidance"
            ]
        case "red-only":
            return [
                e
                for e in events
                if (e.get("type") == "question" and e.get("priority") == PRIORITY_RED)
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

    lines = [f"--- SMM Delta ({len(events)} new events) ---"]

    for e in events:
        eid = e.get("id", "")[:8]
        agent = e.get("agent_id", "")
        content = e.get("content", "")
        etype = e.get("type", "")

        match etype:
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
            case "pair_guidance":
                tool = e.get("tool_name", "")
                lines.append(f"NAVIGATOR [{eid}] (for {tool}): {content}")
            case "customer_input":
                lines.append(f"CUSTOMER: {content}")
            case _:
                lines.append(f"{etype.upper()} [{eid}]: {content}")

    lines.append("--- End SMM Delta ---")
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
    if not smm_dir.exists():
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

    if not smm_dir.exists():
        print(
            f"Error: SMM directory does not exist: {smm_dir}",
            file=sys.stderr,
        )
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
