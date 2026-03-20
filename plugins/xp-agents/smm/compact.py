#!/usr/bin/env python3
"""SMM Log Compaction: curation-watermark-based event archival.

Retention policy (compact_after_curation):
- Keep all events after the curation watermark (not yet curated)
- From pre-watermark events, keep:
  - Last 3 session_end events (for aging calculations)
  - Events referenced by current SMM (unresolved goals, decisions, etc.)
- Archive everything else to backups/archive-{timestamp}.jsonl
- Reset prompt-nugget watermark, update curation watermark
- Remove orphaned .watermark-* files
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
    parse_jsonl,
    read_with_lock,
    replace_events_file,
    resolve_smm_dir,
    write_json_atomic,
    write_watermark,
)
from materialize import read_curation_watermark, write_curation_watermark
from resolution import compute_resolutions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_events(raw: str) -> list[dict]:
    """Parse JSONL text into a list of event dicts, skipping bad lines."""
    events, _ = parse_jsonl(raw)
    return events


# ---------------------------------------------------------------------------
# SMM-referenced ID collection
# ---------------------------------------------------------------------------


def _collect_smm_referenced_ids(events: list[dict]) -> set[str]:
    """Collect IDs of events that are still active in the SMM.

    Active = unresolved goals, non-draft decisions, conventions,
    unresolved concerns/debt/questions/assumptions, open customer_intents,
    retrospective events.
    """
    resolutions = compute_resolutions(events)
    referenced: set[str] = set()

    for event in events:
        eid = event.get("id", "")
        if not eid:
            continue
        etype = event.get("type", "")

        match etype:
            case "goal":
                if eid not in resolutions["resolved_goal_ids"]:
                    referenced.add(eid)
            case "decision":
                is_draft = (event.get("metadata") or {}).get("draft", False)
                if not is_draft and eid not in resolutions["resolved_decision_ids"]:
                    referenced.add(eid)
            case "convention":
                referenced.add(eid)
            case "concern":
                if eid not in resolutions["resolved_concern_ids"]:
                    referenced.add(eid)
            case "debt":
                if eid not in resolutions["resolved_debt_ids"]:
                    referenced.add(eid)
            case "question":
                if eid not in resolutions["answered_question_ids"]:
                    referenced.add(eid)
            case "customer_intent":
                intent_status = event.get("intent_status", "open")
                if intent_status == "open":
                    referenced.add(eid)
            case "assumption":
                if eid not in resolutions["resolved_assumption_ids"]:
                    referenced.add(eid)
            case "retrospective":
                # Keep last 2 for trend detection. _find_unanalyzed_start
                # needs the most recent as a watermark. Full archive in
                # retrospectives/ dir. Handled below with keep_retro_indices.
                pass

    return referenced


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

    Retention policy:
    - Keep all events after the curation watermark (uncurated)
    - From pre-watermark events, keep:
      - Last 3 session_end events (for aging calculations)
      - Events referenced by current SMM (unresolved goals, decisions, etc.)
    - Archive everything else to backups/

    For teams: uses min(event_count) across all curation watermarks.

    Returns {archived: N, retained: N, smm_referenced: N}.
    """
    events_file = smm_dir / "events.jsonl"
    if not events_file.exists():
        return {"archived": 0, "retained": 0, "smm_referenced": 0}

    raw = read_with_lock(events_file)
    events = _parse_events(raw)

    if not events:
        return {"archived": 0, "retained": 0, "smm_referenced": 0}

    # Find the safe compaction boundary (oldest watermark for team safety)
    watermarks = _read_all_curation_watermarks(smm_dir)
    if not watermarks:
        return {"archived": 0, "retained": len(events), "smm_referenced": 0}

    wm_count = watermarks[0]["event_count"]  # min across all agents
    if wm_count <= 0:
        return {"archived": 0, "retained": len(events), "smm_referenced": 0}

    # Watermark may be ahead of actual event count if housekeeping wrote
    # events after setting the watermark. Clamp to actual count.
    wm_count = min(wm_count, len(events))

    # Split at watermark
    pre_watermark = events[:wm_count]
    post_watermark = events[wm_count:]

    # Collect SMM-referenced IDs from ALL events (resolutions may span boundary)
    smm_ids = _collect_smm_referenced_ids(events)

    # Find last 3 session_end events from pre-watermark
    pre_session_ends = [
        i for i, e in enumerate(pre_watermark) if e.get("type") == "session_end"
    ]
    keep_session_end_indices = set(pre_session_ends[-3:])

    # Keep last 2 retro events (trend detection; archive in retrospectives/)
    pre_retros = [
        i for i, e in enumerate(pre_watermark) if e.get("type") == "retrospective"
    ]
    keep_retro_indices = set(pre_retros[-2:])

    # Classify pre-watermark events
    retained: list[dict] = []
    archived: list[dict] = []
    smm_ref_count = 0

    for i, event in enumerate(pre_watermark):
        eid = event.get("id", "")

        if i in keep_session_end_indices or i in keep_retro_indices:
            retained.append(event)
            continue

        if eid in smm_ids:
            retained.append(event)
            smm_ref_count += 1
            continue

        archived.append(event)

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

    try:
        _validate_smm_dir(smm_dir)
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
