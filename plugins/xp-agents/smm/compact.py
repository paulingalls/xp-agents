#!/usr/bin/env python3
"""SMM Log Compaction: curation-watermark-based event archival.

This module is the compaction DRIVER — the lock, the archive write, the atomic
replace, the watermark bookkeeping. The retention POLICY it applies (which
events survive, and for how long) lives in `compact_retention`, imported DOWN
and re-exported here by identity so `compact.X is compact_retention.X`.

Mechanism (compact_after_curation), in order:
- Split events.jsonl at the curation watermark (min across agents in team mode)
- Ask `compact_retention` which pre-watermark events survive; keep all
  post-watermark events unconditionally
- Archive the rest to backups/archive-{timestamp}.jsonl
- Atomic replacement via tempfile + rename under exclusive flock
- Reset prompt-nugget watermark, update curation watermarks
- Remove orphaned .watermark-* files

The policy bullets deliberately do NOT live here — `compact_retention`'s
docstring is their single home, so a retention-rule change has one file to
edit and cannot leave a stale second copy behind.
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
    read_with_lock,
    replace_events_file,
    resolve_smm_dir,
    write_json_atomic,
    write_watermark,
)
from append_validation import parse_jsonl, validate_smm_dir

# Re-exported by identity: importers and their mocks still reach these through
# `compact.` (tests/smm/test_event_schema.py reads
# `compact._COMPACT_INTENTIONALLY_ABSENT`; the AST completeness gate reads the
# match block at its new home). Not a compatibility shim to be deleted later —
# `compact` is the module the rest of the system knows, and the policy split is
# internal to it.
from compact_retention import (  # noqa: F401
    _ASSUMPTION_MAX_AGE,
    _COMPACT_INTENTIONALLY_ABSENT,
    _DECISION_MAX_AGE,
    _classify_pre_watermark,
    _collect_smm_referenced_ids,
    _compute_pending_retro_sprint_ids,
)
from materialize import read_curation_watermark, write_curation_watermark

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_events(raw: str) -> list[dict]:
    """Parse JSONL text into a list of event dicts, skipping bad lines."""
    events, _ = parse_jsonl(raw)
    return events


def _read_all_curation_watermarks(smm_dir: Path) -> list[dict]:
    """Read all curation watermarks. Supports team mode (multiple files).

    Returns list of watermark dicts sorted by event_count ascending.
    """
    watermarks = []

    # Primary watermark
    primary = read_curation_watermark(smm_dir)
    if primary["event_count"] > 0:
        watermarks.append(primary)

    # Team watermarks: .curation-watermark-{agent_id}
    for wm_file in smm_dir.glob(".curation-watermark-*"):
        try:
            raw = wm_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("event_count", 0) > 0:
                watermarks.append(
                    {
                        "event_count": int(data["event_count"]),
                        "timestamp": str(data.get("timestamp", "")),
                        "agent_id": str(data.get("agent_id", "")),
                    }
                )
        except (OSError, json.JSONDecodeError, ValueError):
            continue

    return sorted(watermarks, key=lambda w: w["event_count"])


# ---------------------------------------------------------------------------
# Curation-based compaction
# ---------------------------------------------------------------------------


def compact_after_curation(smm_dir: Path) -> dict:
    """Compact events.jsonl using curation watermark as boundary.

    Everything after the watermark is uncurated and always retained. Which
    PRE-watermark events survive is `compact_retention`'s call
    (`_classify_pre_watermark`) — see that module for the rules.

    For teams: uses min(event_count) across all curation watermarks.

    Returns {archived: N, retained: N, smm_referenced: N,
            watermark_updated: bool}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return {
            "archived": 0,
            "retained": 0,
            "smm_referenced": 0,
            "watermark_updated": False,
        }

    raw = read_with_lock(events_file)
    events = _parse_events(raw)

    if not events:
        return {
            "archived": 0,
            "retained": 0,
            "smm_referenced": 0,
            "watermark_updated": False,
        }

    # Find the safe compaction boundary (oldest watermark for team safety)
    watermarks = _read_all_curation_watermarks(smm_dir)
    if not watermarks:
        return {
            "archived": 0,
            "retained": len(events),
            "smm_referenced": 0,
            "watermark_updated": False,
        }

    wm_count = watermarks[0]["event_count"]  # min across all agents
    if wm_count <= 0:
        return {
            "archived": 0,
            "retained": len(events),
            "smm_referenced": 0,
            "watermark_updated": False,
        }

    # Watermark may be ahead of actual event count if housekeeping wrote
    # events after setting the watermark. Clamp to actual count.
    wm_count = min(wm_count, len(events))

    # Split at watermark
    pre_watermark = events[:wm_count]
    post_watermark = events[wm_count:]

    # Collect SMM-referenced IDs from ALL events (resolutions may span boundary)
    smm_ids = _collect_smm_referenced_ids(events)

    retained, archived, smm_ref_count = _classify_pre_watermark(
        pre_watermark, events, smm_ids
    )

    # All post-watermark events are retained
    retained.extend(post_watermark)

    # Write archive
    if archived:
        backups_dir = smm_dir / "backups"
        backups_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archive_file = backups_dir / f"archive-{ts}.jsonl"
        archive_lines = [json.dumps(e, ensure_ascii=False) for e in archived]
        archive_file.write_text("\n".join(archive_lines) + "\n", encoding="utf-8")

    # Atomic replacement
    replace_events_file(smm_dir, retained)

    # Reset watermarks
    new_count = len(retained)

    # Reset prompt-nugget watermark to post-compaction count
    with contextlib.suppress(OSError):
        write_watermark(smm_dir, "prompt-nugget", new_count)

    # Update curation watermark to reflect new event positions
    # Post-watermark events are at the end; the new curation boundary
    # is at (retained pre-watermark count)
    pre_retained_count = len(retained) - len(post_watermark)
    write_curation_watermark(smm_dir, pre_retained_count, watermarks[0]["agent_id"])

    # Adjust all team curation watermarks by archived count
    archived_count = len(archived)
    if archived_count > 0:
        for wm_file in smm_dir.glob(".curation-watermark-*"):
            try:
                wm_data = json.loads(wm_file.read_text(encoding="utf-8"))
                if isinstance(wm_data, dict) and "event_count" in wm_data:
                    wm_data["event_count"] = max(
                        0, int(wm_data["event_count"]) - archived_count
                    )
                    write_json_atomic(wm_file, wm_data)
            except (OSError, json.JSONDecodeError, ValueError):
                continue

    # Remove orphaned watermark files (keep prompt-nugget and curation)
    for wm in smm_dir.glob(".watermark-*"):
        if wm.name == ".watermark-prompt-nugget":
            continue
        with contextlib.suppress(OSError):
            wm.unlink()

    return {
        "archived": len(archived),
        "retained": new_count,
        "smm_referenced": smm_ref_count,
        "watermark_updated": True,
    }


# ---------------------------------------------------------------------------
# Legacy entry point (delegates to curation-based compaction)
# ---------------------------------------------------------------------------


def compact(smm_dir: Path, keep_sessions: int = 3) -> dict:
    """Compact events.jsonl using curation-watermark-based policy.

    The keep_sessions parameter is ignored — retained for API compatibility.
    Delegates to compact_after_curation() which uses the curation watermark
    as the compaction boundary.

    Returns {archived: N, retained: N, permanent: N}.
    """
    result = compact_after_curation(smm_dir)
    # Map new keys to legacy keys for backward compatibility
    return {
        "archived": result["archived"],
        "retained": result["retained"],
        "permanent": result["smm_referenced"],
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
        "--smm-dir",
        type=Path,
        help="Override SMM directory (default: auto-detect from git)",
    )
    args = parser.parse_args()

    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()
    if smm_dir is None:
        # Graceful degradation when not in a git repo
        sys.exit(0)

    try:
        validate_smm_dir(smm_dir)
    except ValueError:
        # Graceful degradation when SMM not initialized
        sys.exit(0)

    try:
        result = compact(smm_dir)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Compacted: {result['archived']} archived, "
        f"{result['retained']} retained ({result['permanent']} permanent)"
    )


if __name__ == "__main__":
    main()
