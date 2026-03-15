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
import fcntl
import json
import os
import signal
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import (
    LockTimeoutError,
    _on_alarm,
    _safe_open_nofollow,
    _validate_smm_dir,
    compute_resolutions,
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
# Core logic
# ---------------------------------------------------------------------------


def compact(smm_dir: Path, keep_sessions: int = 3) -> dict:
    """Compact events.jsonl: archive old events, keep permanent + recent.

    Returns {archived: N, retained: N, permanent: N}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return {"archived": 0, "retained": 0, "permanent": 0}

    # Read all events
    events: list[dict] = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue

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
    # The cutoff position is the session_end that starts the "keep" window
    cutoff_idx = session_end_positions[-(keep_sessions)]
    # Events at and after cutoff_idx are in recent sessions
    # Events before cutoff_idx are candidates for archival

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
            # In recent sessions — always retain
            retained.append(event)
            continue

        event_type = event.get("type", "")
        event_id = event.get("id", "")

        # Permanent types never archived
        if event_type in PERMANENT_TYPES:
            retained.append(event)
            permanent_count += 1
            continue

        # Unresolved questions retained
        if event_type == "question" and event_id not in answered_ids:
            retained.append(event)
            continue

        # Unresolved concerns retained
        if event_type == "concern" and event_id not in resolved_ids:
            retained.append(event)
            continue

        # Everything else: archive
        archived.append(event)

    # Write archive
    if archived:
        backups_dir = smm_dir / "backups"
        backups_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archive_file = backups_dir / f"archive-{ts}.jsonl"
        archive_lines = [json.dumps(e, ensure_ascii=False) for e in archived]
        archive_file.write_text("\n".join(archive_lines) + "\n", encoding="utf-8")

    # Atomic replacement of events.jsonl
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

        # Write retained events to temp file, then rename
        retained_lines = [json.dumps(e, ensure_ascii=False) for e in retained]
        fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(retained_lines) + ("\n" if retained_lines else ""))
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
    # When called as a PostCompact hook, stdin has JSON. Try reading it.
    # When called from CLI, use argparse.
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                json.loads(raw)
        except (json.JSONDecodeError, OSError):
            pass

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
