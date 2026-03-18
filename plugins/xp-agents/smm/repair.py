#!/usr/bin/env python3
"""SMM Log Repair: rebuild events.jsonl from corrupted log.

- Skip malformed JSON lines
- Skip events missing required fields (id, type, ts, agent_id, content)
- Deduplicate by event ID (keep first occurrence)
- Sort by timestamp
- Back up original to backups/pre-repair-{timestamp}.jsonl
- Write .repair-report.json with counts
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import (
    LockTimeoutError,
    _validate_smm_dir,
    replace_events_file,
    resolve_smm_dir,
)

# Required fields — same set validated by _append_impl.validate_event()
_REQUIRED_FIELDS = {"id", "type", "ts", "agent_id", "content"}

_EMPTY_RESULT = {
    "malformed": 0,
    "invalid": 0,
    "duplicates": 0,
    "reordered": 0,
    "retained": 0,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def repair(smm_dir: Path, dry_run: bool = False) -> dict:
    """Repair events.jsonl: skip bad lines, dedup, sort.

    Returns {malformed: N, invalid: N, duplicates: N, reordered: N, retained: N}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return dict(_EMPTY_RESULT)

    raw = events_file.read_text(encoding="utf-8")
    if not raw.strip():
        return dict(_EMPTY_RESULT)

    # Phase 1: Single-pass parse, validate, dedup
    malformed = 0
    invalid = 0
    duplicates = 0
    valid_events: list[dict] = []
    seen_ids: set[str] = set()

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue

        if not isinstance(obj, dict):
            invalid += 1
            continue

        if not _REQUIRED_FIELDS.issubset(obj.keys()):
            invalid += 1
            continue

        event_id = obj["id"]
        if event_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(event_id)

        valid_events.append(obj)

    # Phase 2: Sort by timestamp
    original_order = [e["id"] for e in valid_events]
    valid_events.sort(key=lambda e: e.get("ts", ""))
    sorted_order = [e["id"] for e in valid_events]
    reordered = 1 if original_order != sorted_order else 0

    result = {
        "malformed": malformed,
        "invalid": invalid,
        "duplicates": duplicates,
        "reordered": reordered,
        "retained": len(valid_events),
    }

    if dry_run:
        return result

    # Phase 3: Back up original
    backups_dir = smm_dir / "backups"
    backups_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup_file = backups_dir / f"pre-repair-{ts}.jsonl"
    backup_file.write_text(raw, encoding="utf-8")

    # Phase 4: Atomic replacement under exclusive flock
    replace_events_file(smm_dir, valid_events)

    # Phase 5: Write repair report
    report_file = smm_dir / ".repair-report.json"
    report_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair corrupted SMM event log")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report problems without modifying files",
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
        result = repair(smm_dir, dry_run=args.dry_run)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(
        f"{prefix}Repair: {result['malformed']} malformed, "
        f"{result['invalid']} invalid, {result['duplicates']} duplicates, "
        f"{result['reordered']} reordered, {result['retained']} retained"
    )


if __name__ == "__main__":
    main()
