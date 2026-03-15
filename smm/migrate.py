#!/usr/bin/env python3
"""SMM Schema Migration: additive-only schema versioning.

Framework for upgrading events between schema versions.
Events with schema_version > CURRENT_VERSION pass through unchanged
(forward-compatible).
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import (
    LockTimeoutError,
    _on_alarm,
    _safe_open_nofollow,
    _validate_smm_dir,
    resolve_smm_dir,
)

# ---------------------------------------------------------------------------
# Version & migrations
# ---------------------------------------------------------------------------

CURRENT_VERSION = 2

# Regex to detect timezone in ISO 8601 timestamp
_TZ_RE = re.compile(r"[+-]\d{2}:\d{2}$|Z$")


def _migrate_v1_to_v2(event: dict) -> dict:
    """v1→v2: set schema_version=2, normalize ts to include timezone."""
    event = dict(event)
    event["schema_version"] = 2

    ts = event.get("ts", "")
    if ts and not _TZ_RE.search(ts):
        event["ts"] = ts + "+00:00"

    return event


MIGRATIONS: dict[tuple[int, int], callable] = {
    (1, 2): _migrate_v1_to_v2,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def migrate_event(event: dict) -> dict:
    """Upgrade a single event to CURRENT_VERSION.

    Events with schema_version > CURRENT_VERSION pass through unchanged.
    """
    version = event.get("schema_version", 1)

    # Future versions pass through
    if version > CURRENT_VERSION:
        return event

    # Apply migrations sequentially
    current = dict(event)
    while version < CURRENT_VERSION:
        migration = MIGRATIONS.get((version, version + 1))
        if migration is None:
            break
        current = migration(current)
        version = current.get("schema_version", version + 1)

    return current


def migrate_file(smm_dir: Path) -> dict:
    """Upgrade all events in events.jsonl atomically.

    Returns {migrated: N, unchanged: N}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return {"migrated": 0, "unchanged": 0}

    raw = events_file.read_text(encoding="utf-8")
    if not raw.strip():
        return {"migrated": 0, "unchanged": 0}

    events: list[dict] = []
    migrated_count = 0
    unchanged_count = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                events.append(event)
                unchanged_count += 1
                continue
        except json.JSONDecodeError:
            unchanged_count += 1
            continue

        version = event.get("schema_version", 1)
        migrated = migrate_event(event)

        if migrated.get("schema_version") != version or migrated != event:
            migrated_count += 1
        else:
            unchanged_count += 1

        events.append(migrated)

    # If nothing migrated, skip file write
    if migrated_count == 0:
        return {"migrated": 0, "unchanged": unchanged_count}

    # Atomic replacement
    lock_file = smm_dir / "events.lock"
    lock_fd = None
    raw_fd = None

    try:
        raw_fd = _safe_open_nofollow(lock_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
            os.chmod(tmp, 0o600)
            os.rename(tmp, events_file)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    return {"migrated": migrated_count, "unchanged": unchanged_count}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate SMM events to current schema version"
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
        result = migrate_file(smm_dir)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Migration: {result['migrated']} migrated, "
        f"{result['unchanged']} unchanged "
        f"(current schema version: {CURRENT_VERSION})"
    )


if __name__ == "__main__":
    main()
