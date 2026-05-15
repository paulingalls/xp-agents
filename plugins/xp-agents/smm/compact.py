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

import event_schema as es
import resolution
import session_history
from _append_impl import (
    LockTimeoutError,
    read_with_lock,
    replace_events_file,
    resolve_smm_dir,
    write_json_atomic,
    write_watermark,
)
from append_validation import parse_jsonl, validate_smm_dir
from materialize import read_curation_watermark, write_curation_watermark

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


_DECISION_MAX_AGE = 3  # Sessions before unresolved decisions can compact
_ASSUMPTION_MAX_AGE = 5  # Sessions before unresolved assumptions/questions can compact

# Event types intentionally NOT collected by _collect_smm_referenced_ids.
# Derived from EVENT_CATEGORY with two named-set overrides:
#   - TRANSIENT types EXCEPT goal (goal is retained as a cross-session
#     intent marker even though it's not curated).
#   - SESSION_END + SESSION_SUMMARY: sibling_artifact types with separate
#     index-based retention (session_history.json holds the last 3
#     summaries; events.jsonl drops them).
#   - ANSWER + DISCOVERY + CUSTOMER_INPUT: their lifecycle is tied to a
#     referenced event (answer→question, discovery→assumption) or they're
#     superseded by another type (customer_input→customer_intent). Not
#     SMM-referenced on their own, so they compact away.
# Test gate: tests/engine/test_compact.py::TestEventTypeMatchCompleteness
# fails if a new EVENT_TYPE_* lacks a `case` arm here AND isn't covered
# by the derivation below.
_COMPACT_INDEX_RETENTION_TYPES = frozenset(
    {es.EVENT_TYPE_SESSION_END, es.EVENT_TYPE_SESSION_SUMMARY}
)
_COMPACT_REFERENCE_TIED_TYPES = frozenset(
    {es.EVENT_TYPE_ANSWER, es.EVENT_TYPE_DISCOVERY, es.EVENT_TYPE_CUSTOMER_INPUT}
)
_COMPACT_INTENTIONALLY_ABSENT = frozenset(
    t
    for t in es.VALID_TYPES
    if (
        (
            es.event_category_of(t) == es.EVENT_CATEGORY.TRANSIENT
            and t != es.EVENT_TYPE_GOAL
        )
        or t in _COMPACT_INDEX_RETENTION_TYPES
        or t in _COMPACT_REFERENCE_TIED_TYPES
    )
)


def _compute_pending_retro_sprint_ids(events: list[dict]) -> set[str]:
    """Sprint IDs started but with no sprint_retro_done event yet.

    Includes both active sprints (no sprint_end) and ended-but-not-retro'd
    sprints. Their commit events must stay in events.jsonl so the eventual
    /xp-sprint-review can compute per-story metrics.
    """
    started: set[str] = set()
    retro_done: set[str] = set()
    for e in events:
        meta = e.get("metadata") or {}
        sid = meta.get("sprint_id")
        if not sid:
            continue
        etype = e.get("type")
        if (
            etype == es.EVENT_TYPE_SPRINT
            and meta.get("action") == es.SPRINT_ACTION_START
        ):
            started.add(sid)
        elif (
            etype == es.EVENT_TYPE_STATUS
            and meta.get("action") == es.STATUS_ACTION_SPRINT_RETRO_DONE
        ):
            retro_done.add(sid)
    return started - retro_done


def _collect_smm_referenced_ids(events: list[dict]) -> set[str]:
    """Collect IDs of events that are still active in the SMM.

    Active = unresolved goals, decisions/assumptions/questions (< 3 sessions old),
    conventions, unresolved concerns/debt, open customer_intents, sprint_starts
    of pending-retro sprints, and commits whose sprint_id is pending-retro
    (so /xp-sprint-review can compute per-story metrics).
    Retrospectives kept via separate retention logic (last 2).
    """
    resolutions = resolution.compute_resolutions(events)
    referenced: set[str] = set()

    # Build session_end timestamps for decision aging. Sort is required —
    # sessions_since_event uses bisect_right on this list.
    se_timestamps = session_history.filter_session_end_timestamps(events)

    pending_retro_sprint_ids = _compute_pending_retro_sprint_ids(events)

    for event in events:
        eid = event.get("id", "")
        if not eid:
            continue
        etype = event.get("type", "")

        match etype:
            case es.EVENT_TYPE_GOAL:
                if eid not in resolutions["resolved_goal_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_DECISION:
                if eid in resolutions["resolved_decision_ids"]:
                    continue
                # Age-based: keep for _DECISION_MAX_AGE sessions
                decision_ts = event.get("ts", "")
                sessions_after = es.sessions_since_event(se_timestamps, decision_ts)
                if sessions_after < _DECISION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_CONVENTION:
                referenced.add(eid)
            case es.EVENT_TYPE_CONCERN:
                if eid not in resolutions["resolved_concern_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_DEBT:
                if eid not in resolutions["resolved_debt_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_QUESTION:
                if eid in resolutions["answered_question_ids"]:
                    continue
                # Age-based: compact unanswered questions
                q_ts = event.get("ts", "")
                q_sessions = es.sessions_since_event(se_timestamps, q_ts)
                if q_sessions < _ASSUMPTION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_CUSTOMER_INTENT:
                intent_status = event.get("intent_status", "open")
                if intent_status == "open":
                    referenced.add(eid)
            case es.EVENT_TYPE_ASSUMPTION:
                if eid in resolutions["resolved_assumption_ids"]:
                    continue
                # Age-based: compact unresolved assumptions
                a_ts = event.get("ts", "")
                a_sessions = es.sessions_since_event(se_timestamps, a_ts)
                if a_sessions < _ASSUMPTION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_SPRINT:
                meta = event.get("metadata", {})
                action = meta.get("action", "")
                sprint_id = meta.get("sprint_id", "")
                # Sprint starts retained until retro_done fires — keeps
                # _compute_pending_retro_sprint_ids able to identify the
                # sprint across multiple compaction rounds. Sprint ends
                # handled by index-based retention below.
                if (
                    action == es.SPRINT_ACTION_START
                    and sprint_id in pending_retro_sprint_ids
                ):
                    referenced.add(eid)
            case es.EVENT_TYPE_RETROSPECTIVE:
                # Keep last 2 for trend detection. _find_unanalyzed_start
                # needs the most recent as a watermark. Full archive in
                # retrospectives/ dir. Handled below with keep_retro_indices.
                pass
            case es.EVENT_TYPE_COMMIT:
                sid = (event.get("metadata") or {}).get("sprint_id")
                if sid and sid in pending_retro_sprint_ids:
                    referenced.add(eid)

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
# Pre-watermark event classification
# ---------------------------------------------------------------------------


def _classify_pre_watermark(
    pre_watermark: list[dict],
    all_events: list[dict],
    smm_ids: set[str],
) -> tuple[list[dict], list[dict], int]:
    """Classify pre-watermark events as retained or archived.

    Retention rules (checked in order):
    1. Last 3 session_end events (for aging calculations)
    2. Last 2 retrospective events (for trend detection)
    3. Last 1 sprint end event (for velocity data)
    4. sprint_retro_done status events paired with retained sprint_end
       (so needs_sprint_retro detection stays correct after compaction)
    5. SMM-referenced events (unresolved goals, active decisions, etc.)
    6. Everything else → archived

    Returns (retained, archived, smm_ref_count).
    """
    # Find last 3 session_end events from pre-watermark
    pre_session_ends = [
        i
        for i, e in enumerate(pre_watermark)
        if e.get("type") == es.EVENT_TYPE_SESSION_END
    ]
    keep_session_end_indices = set(pre_session_ends[-3:])

    # Keep last 2 retro events across ALL events (not just pre-watermark).
    # Post-watermark retros count toward the cap so we don't accumulate 3+.
    all_retro_ids = [
        e.get("id", "")
        for e in all_events
        if e.get("type") == es.EVENT_TYPE_RETROSPECTIVE
    ]
    keep_retro_ids = set(all_retro_ids[-2:])
    pre_retro_indices = {
        i
        for i, e in enumerate(pre_watermark)
        if e.get("type") == es.EVENT_TYPE_RETROSPECTIVE
        and e.get("id", "") in keep_retro_ids
    }

    # Keep last 1 sprint end event across ALL events (velocity data).
    # Post-watermark sprint ends count toward the cap.
    def _is_sprint_end(e: dict) -> bool:
        return (
            e.get("type") == es.EVENT_TYPE_SPRINT
            and e.get("metadata", {}).get("action") == es.SPRINT_ACTION_END
        )

    all_sprint_end_ids = [e.get("id", "") for e in all_events if _is_sprint_end(e)]
    keep_sprint_end_ids = set(all_sprint_end_ids[-1:])
    pre_sprint_end_indices = {
        i
        for i, e in enumerate(pre_watermark)
        if _is_sprint_end(e) and e.get("id", "") in keep_sprint_end_ids
    }

    # Keep sprint_retro_done events whose sprint_id matches a retained
    # sprint_end. Sprint-id-paired rule keeps detection correct after
    # compaction — needs_sprint_retro would otherwise re-fire on a
    # retained sprint_end whose paired retro_done was archived.
    retained_sprint_ids: set[str] = set()
    for e in all_events:
        if _is_sprint_end(e) and e.get("id", "") in keep_sprint_end_ids:
            sid = e.get("metadata", {}).get("sprint_id")
            if sid:
                retained_sprint_ids.add(sid)

    def _is_paired_retro_done(e: dict) -> bool:
        if e.get("type") != es.EVENT_TYPE_STATUS:
            return False
        metadata = e.get("metadata") or {}
        return (
            metadata.get("action") == es.STATUS_ACTION_SPRINT_RETRO_DONE
            and metadata.get("sprint_id") in retained_sprint_ids
        )

    pre_retro_done_indices = {
        i for i, e in enumerate(pre_watermark) if _is_paired_retro_done(e)
    }

    retained: list[dict] = []
    archived: list[dict] = []
    smm_ref_count = 0

    for i, event in enumerate(pre_watermark):
        eid = event.get("id", "")

        if (
            i in keep_session_end_indices
            or i in pre_retro_indices
            or i in pre_sprint_end_indices
            or i in pre_retro_done_indices
        ):
            retained.append(event)
            continue

        if eid in smm_ids:
            retained.append(event)
            smm_ref_count += 1
            continue

        archived.append(event)

    return retained, archived, smm_ref_count


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
