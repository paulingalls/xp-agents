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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import archive
from _append_impl import (
    LockTimeoutError,
    replace_events_file,
    resolve_smm_dir,
)
from append_validation import validate_smm_dir
from event_schema import REQUIRED_FIELDS as _REQUIRED_FIELDS

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
    kept_ids: set[str] = set()
    # EVERY id this pass parsed, valid or not — deliberately NOT `kept_ids`.
    # This is what `replace_events_file` is told we SAW, and it drops what it
    # saw and we did not keep. Hand it `kept_ids` instead and every event this
    # pass counted as invalid reads back as "arrived concurrently", so repair
    # would preserve exactly what it had just decided to delete.
    parsed_ids: set[str] = set()

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

        if isinstance(obj.get("id"), str):
            parsed_ids.add(obj["id"])

        if not _REQUIRED_FIELDS.issubset(obj.keys()):
            invalid += 1
            continue

        event_id = obj["id"]
        if event_id in kept_ids:
            duplicates += 1
            continue
        kept_ids.add(event_id)

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

    # Phase 3: Back up original. Never-clobbering: phase 4 DROPS the malformed
    # and invalid lines, so this backup is their only copy — a same-second second
    # repair that overwrote it would annihilate them (see `archive.write_archive`).
    archive.write_archive(smm_dir / "backups", "pre-repair", raw)

    # Phase 4: Atomic replacement under exclusive flock. An event appended
    # while phases 1-3 ran is unknown to `parsed_ids`, so it survives the
    # rewrite; the invalid and duplicate events ARE known, so they still go.
    # (A malformed line has no id to be known by — `replace_events_file`
    # drops it on that basis, which is what lets repair still repair.)
    replace_events_file(smm_dir, valid_events, seen_ids=parsed_ids)

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
    if smm_dir is None:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    try:
        validate_smm_dir(smm_dir)
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
