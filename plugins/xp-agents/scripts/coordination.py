#!/usr/bin/env python3
"""Coordination file management for multi-agent conflict detection.

Manages .coordination.json — a lightweight, lockable file that tracks
which agent is working on which files, enabling O(1) overlap checks.
"""

import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import write_json_atomic

_COORDINATION_FILE = ".coordination.json"
_COORDINATION_LOCK = ".coordination.lock"
_COORDINATION_MAX_AGE = 1800  # 30 minutes


def update_coordination(smm_dir: Path, agent_id: str, working_on: list[str]) -> None:
    """Atomically update this agent's entry in .coordination.json."""
    import fcntl
    import signal

    lock_path = smm_dir / _COORDINATION_LOCK
    coord_path = smm_dir / _COORDINATION_FILE

    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return

    try:
        old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(2)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (OSError, SystemExit):
            return
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        # Read existing data
        data: dict = {}
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            data = json.loads(coord_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        # Update agent entry
        from _common import now_iso

        data[agent_id] = {
            "working_on": working_on,
            "updated": now_iso(),
        }

        write_json_atomic(coord_path, data)
    finally:
        os.close(lock_fd)


def read_coordination(
    smm_dir: Path, max_age_seconds: int = _COORDINATION_MAX_AGE
) -> dict:
    """Read .coordination.json, filtering out stale entries."""
    coord_path = smm_dir / _COORDINATION_FILE
    try:
        data = json.loads(coord_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result: dict = {}
    for aid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        updated_str = entry.get("updated", "")
        try:
            updated = datetime.fromisoformat(updated_str)
            if (now - updated).total_seconds() <= max_age_seconds:
                result[aid] = entry
        except (ValueError, TypeError):
            continue
    return result


def has_active_teammates(smm_dir: Path, agent_id: str) -> bool:
    """Return True if other non-stale agents are active in coordination."""
    coord = read_coordination(smm_dir)
    return any(aid != agent_id for aid in coord)


def clear_coordination_agent(smm_dir: Path, agent_id: str) -> None:
    """Remove an agent's entry from .coordination.json."""
    import fcntl
    import signal

    coord_path = smm_dir / _COORDINATION_FILE
    lock_path = smm_dir / _COORDINATION_LOCK

    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return

    try:
        old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(2)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (OSError, SystemExit):
            return
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        data: dict = {}
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            data = json.loads(coord_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        if agent_id in data:
            del data[agent_id]
            write_json_atomic(coord_path, data)
    finally:
        os.close(lock_fd)
