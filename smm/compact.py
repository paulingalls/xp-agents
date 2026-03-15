#!/usr/bin/env python3
"""SMM Log Compaction: archive old events, keep permanent + recent sessions.

Retention policy:
- Keep events from the last N sessions (delimited by session_end events)
- Permanent events never archived: decision, convention, goal, debt,
  assumption, retrospective
- Unresolved questions/concerns retained
- Archived events written to backups/archive-{timestamp}.jsonl
- All .watermark-* files removed after compaction
- Atomic replacement via tempfile + rename under exclusive flock
"""

import argparse
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import (
    LockTimeoutError,
    _validate_smm_dir,
    compute_resolutions,
    replace_events_file,
    resolve_smm_dir,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERMANENT_TYPES = frozenset(
    {
        "decision",
        "convention",
        "goal",
        "debt",
        "assumption",
        "retrospective",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_events(raw: str) -> list[dict]:
    """Parse JSONL text into a list of event dicts, skipping bad lines."""
    events: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue
    return events


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compact(smm_dir: Path, keep_sessions: int = 3) -> dict:
    """Compact events.jsonl: archive old events, keep permanent + recent.

    Returns {archived: N, retained: N, permanent: N}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return {"archived": 0, "retained": 0, "permanent": 0}

    # Read all events (initial read; replace_events_file will re-read under lock)
    raw = events_file.read_text(encoding="utf-8")
    events = _parse_events(raw)

    if not events:
        return {"archived": 0, "retained": 0, "permanent": 0}

    # Find session boundaries (session_end events)
    session_end_positions = [
        i for i, e in enumerate(events) if e.get("type") == "session_end"
    ]

    # If fewer sessions than threshold, nothing to archive
    if len(session_end_positions) < keep_sessions:
        return {"archived": 0, "retained": len(events), "permanent": 0}

    # Cutoff: keep events from the last keep_sessions sessions
    cutoff_idx = session_end_positions[-(keep_sessions)]

    # Compute resolutions for retention decisions
    resolutions = compute_resolutions(events)
    answered_ids = resolutions["answered_question_ids"]
    resolved_ids = resolutions["resolved_concern_ids"]

    # Classify events
    retained: list[dict] = []
    archived: list[dict] = []
    permanent_count = 0

    for i, event in enumerate(events):
        if i >= cutoff_idx:
            retained.append(event)
            continue

        event_type = event.get("type", "")
        event_id = event.get("id", "")

        if event_type in PERMANENT_TYPES:
            retained.append(event)
            permanent_count += 1
            continue

        if event_type == "question" and event_id not in answered_ids:
            retained.append(event)
            continue

        if event_type == "concern" and event_id not in resolved_ids:
            retained.append(event)
            continue

        archived.append(event)

    # Write archive
    if archived:
        backups_dir = smm_dir / "backups"
        backups_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archive_file = backups_dir / f"archive-{ts}.jsonl"
        archive_lines = [json.dumps(e, ensure_ascii=False) for e in archived]
        archive_file.write_text("\n".join(archive_lines) + "\n", encoding="utf-8")

    # Atomic replacement under exclusive flock
    replace_events_file(smm_dir, retained)

    # Remove all watermark files
    for wm in smm_dir.glob(".watermark-*"):
        with contextlib.suppress(OSError):
            wm.unlink()

    return {
        "archived": len(archived),
        "retained": len(retained),
        "permanent": permanent_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    # When called as a PostCompact hook, stdin has JSON — consume it.
    if not sys.stdin.isatty():
        with contextlib.suppress(OSError):
            sys.stdin.read()

    parser = argparse.ArgumentParser(
        description="Compact SMM event log: archive old events"
    )
    parser.add_argument(
        "--keep-sessions",
        type=int,
        default=3,
        help="Number of recent sessions to keep (default: 3)",
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
    except ValueError:
        # Graceful degradation when SMM not initialized
        sys.exit(0)

    try:
        result = compact(smm_dir, keep_sessions=args.keep_sessions)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Compacted: {result['archived']} archived, "
        f"{result['retained']} retained ({result['permanent']} permanent)"
    )


if __name__ == "__main__":
    main()
