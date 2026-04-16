#!/usr/bin/env python3
"""SMM Schema Migration: additive-only schema versioning.

Framework for upgrading events between schema versions.
Events with schema_version > CURRENT_VERSION pass through unchanged
(forward-compatible).
"""

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import (
    LockTimeoutError,
    _validate_smm_dir,
    parse_jsonl,
    replace_events_file,
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


MIGRATIONS: dict[tuple[int, int], Callable] = {
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

    parsed, skipped = parse_jsonl(raw)
    migrated_count = 0
    unchanged_count = skipped

    events: list[dict] = []
    for event in parsed:
        version = event.get("schema_version", 1)
        migrated = migrate_event(event)

        if migrated.get("schema_version") != version:
            migrated_count += 1
        else:
            unchanged_count += 1

        events.append(migrated)

    # If nothing migrated, skip file write
    if migrated_count == 0:
        return {"migrated": 0, "unchanged": unchanged_count}

    # Atomic replacement under exclusive flock
    replace_events_file(smm_dir, events)

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
    if smm_dir is None:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

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
