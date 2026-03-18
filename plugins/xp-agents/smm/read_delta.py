#!/usr/bin/env python3
"""SMM Delta Reader: per-agent watermark-based event reads.

Reads new events since an agent's last read position.
Watermark advances after each read.
"""

from pathlib import Path

from _append_impl import (
    _validate_agent_id,
    _validate_smm_dir,
    parse_jsonl,
    write_watermark,
)
from _append_impl import (
    read_with_lock as _read_with_lock,
)


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

    if start_line >= total:
        return [], total

    # Parse only the tail portion without split-join-split overhead
    # Find byte offset of start_line in raw string
    offset = 0
    for _ in range(start_line):
        offset = raw.index("\n", offset) + 1
    events, _ = parse_jsonl(raw[offset:])

    return events, total


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def read_delta(
    smm_dir: Path,
    agent_id: str,
    update_watermark: bool = True,
) -> list[dict]:
    """Read new events for agent since last watermark. Returns event list."""
    try:
        _validate_smm_dir(smm_dir)
    except ValueError:
        return []

    watermark = read_watermark(smm_dir, agent_id)
    events, total_lines = read_events_from(smm_dir, watermark)

    if update_watermark and total_lines > watermark:
        write_watermark(smm_dir, agent_id, total_lines)

    return events
