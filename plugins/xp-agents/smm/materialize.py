#!/usr/bin/env python3
"""SMM Materializer: event parsing, index building, and curation data.

Parses the append-only event log, builds indices for lookups, and
prepares structured curation data for the housekeeping skill.
"""

import ast
import json
import logging
from collections import Counter
from pathlib import Path

import event_schema
import resolution
import smm_store
from _append_impl import (
    now_iso,
    write_json_atomic,
)
from _append_impl import (
    read_with_lock as _read_with_lock,
)
from append_validation import parse_jsonl
from event_schema import METADATA_KEY_RESOLVES, sessions_since_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curation watermark (M1)
# ---------------------------------------------------------------------------

_CURATION_WM_DEFAULTS = {"event_count": 0, "timestamp": "", "agent_id": ""}


def write_curation_watermark(smm_dir: Path, event_count: int, agent_id: str) -> None:
    """Atomic write of curation watermark via tempfile + rename."""
    wm_file = smm_dir / ".curation-watermark"
    if wm_file.is_symlink():
        raise OSError(f"Curation watermark path is a symlink: {wm_file}")

    data = {
        "event_count": event_count,
        "timestamp": now_iso(),
        "agent_id": agent_id,
    }
    write_json_atomic(wm_file, data)


def read_curation_watermark(smm_dir: Path) -> dict:
    """Read curation watermark. Returns defaults if missing/corrupt."""
    wm_file = smm_dir / ".curation-watermark"
    try:
        raw = wm_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return dict(_CURATION_WM_DEFAULTS)
        return {
            "event_count": int(data.get("event_count", 0)),
            "timestamp": str(data.get("timestamp", "")),
            "agent_id": str(data.get("agent_id", "")),
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return dict(_CURATION_WM_DEFAULTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_events(smm_dir: Path) -> tuple[list[dict], int]:
    """Read events.jsonl under shared flock, validate required fields.

    Uses parse_jsonl() for core JSONL parsing, then validates that each
    event has 'id' and 'type' fields.
    """
    raw = _read_with_lock(smm_dir / "events.jsonl")
    if not raw.strip():
        return [], 0

    parsed, skipped = parse_jsonl(raw)

    # Additional validation: require id and type fields
    events: list[dict] = []
    for event in parsed:
        if "id" not in event or "type" not in event:
            logger.warning("Event missing id or type, skipping")
            skipped += 1
            continue
        events.append(event)

    return events, skipped


def _extract_retro_history(retro_events: list[dict]) -> dict:
    """Extract retrospective history from retrospective events.

    Args:
        retro_events: Pre-filtered list of retrospective events.

    Returns dict with latest_tries, recurring_fixes, adopted_tries.
    """
    if not retro_events:
        return {"latest_tries": [], "recurring_fixes": [], "adopted_tries": []}

    # Sort by timestamp to find latest
    retros_sorted = sorted(retro_events, key=lambda e: e.get("ts", ""))

    # latest_tries: try items from most recent retro
    latest = retros_sorted[-1]
    latest_tries = [item.get("content", "") for item in latest.get("try", [])]

    # recurring_fixes: fix content appearing in 3+ retros
    fix_counter: Counter[str] = Counter()
    for r in retros_sorted:
        # Count each fix content once per retro (deduplicate within a retro)
        seen_in_retro: set[str] = set()
        for item in r.get("fix", []):
            content = item.get("content", "")
            if content and content not in seen_in_retro:
                seen_in_retro.add(content)
                fix_counter[content] += 1

    recurring_fixes = [content for content, count in fix_counter.items() if count >= 3]

    # adopted_tries: try items from earlier retros that don't appear in
    # later fix items (the try worked — no longer a problem)
    all_fix_contents: set[str] = set()
    for r in retros_sorted:
        for item in r.get("fix", []):
            content = item.get("content", "")
            if content:
                all_fix_contents.add(content)

    adopted_tries: list[str] = []
    for r in retros_sorted[:-1]:  # exclude latest
        for item in r.get("try", []):
            content = item.get("content", "")
            if (
                content
                and content not in all_fix_contents
                and content not in adopted_tries
            ):
                adopted_tries.append(content)

    return {
        "latest_tries": latest_tries,
        "recurring_fixes": recurring_fixes,
        "adopted_tries": adopted_tries[-10:],
    }


def _empty_new_since() -> dict:
    """Canonical empty new_since_last_curation shape."""
    return {
        "customer_inputs": [],
        "decisions": [],
        "concerns": [],
        "assumptions": [],
        "debt": [],
        "questions": [],
        "resolutions": [],
        "resolved_concern_count": 0,
    }


def _empty_retro_history() -> dict:
    """Canonical empty retro_history shape."""
    return {"latest_tries": [], "recurring_fixes": [], "adopted_tries": []}


def _health_from_smm(current_smm: dict) -> dict:
    """Pillar counts for the health check."""
    return {
        "intent_count": len(current_smm.get("intent", [])),
        "constraints_count": len(current_smm.get("constraints", [])),
        "risks_count": len(current_smm.get("risks", [])),
        "wisdom_count": len(current_smm.get("wisdom", [])),
    }


_CUSTOMER_INPUT_TRUNCATE_LIMIT = 300


def _normalize_customer_input(summary: dict) -> dict:
    """Normalize AskUserQuestion content and truncate long prompts.

    AskUserQuestion responses are Python repr dicts — detect and
    re-serialize as compact Q/A pairs. Plain prompts >300 chars get
    truncated with a content_truncated flag.
    """
    summary = dict(summary)
    content = summary.get("content", "")

    if content.startswith("{'questions':") and "'answers':" in content:
        try:
            parsed = ast.literal_eval(content)
            answers = parsed.get("answers", {})
            questions = parsed.get("questions", [])
            pairs = []
            for q in questions:
                q_text = q.get("question", "")
                a_text = answers.get(q_text, "")
                pairs.append(f"Q: {q_text} → A: {a_text}")
            summary["content"] = "; ".join(pairs)
            return summary
        except (ValueError, SyntaxError):
            pass

    if len(content) > _CUSTOMER_INPUT_TRUNCATE_LIMIT:
        summary["content"] = content[:_CUSTOMER_INPUT_TRUNCATE_LIMIT]
        summary["content_truncated"] = True

    return summary


def _bucket_new_events(
    new_events: list[dict],
    resolved_concern_ids: set,
) -> dict:
    """Bucket new events into new_since_last_curation pillars."""
    new_since: dict = _empty_new_since()
    new_since["resolved_concern_count"] = len(resolved_concern_ids)

    for e in new_events:
        etype = e.get("type", "")
        summary = {
            "id": e.get("id", ""),
            "content": e.get("content", ""),
            "ts": e.get("ts", ""),
            "agent_id": e.get("agent_id", ""),
        }
        match etype:
            case event_schema.EVENT_TYPE_CUSTOMER_INPUT:
                new_since["customer_inputs"].append(_normalize_customer_input(summary))
            case event_schema.EVENT_TYPE_DECISION:
                summary["topic"] = e.get("topic", "")
                new_since["decisions"].append(summary)
            case event_schema.EVENT_TYPE_CONCERN:
                if e.get("id", "") not in resolved_concern_ids:
                    new_since["concerns"].append(summary)
            case event_schema.EVENT_TYPE_ASSUMPTION:
                new_since["assumptions"].append(summary)
            case event_schema.EVENT_TYPE_DEBT:
                summary["files"] = e.get("files", [])
                new_since["debt"].append(summary)
            case event_schema.EVENT_TYPE_QUESTION:
                summary["priority"] = e.get("priority", "")
                new_since["questions"].append(summary)

        # Track resolutions in new events
        for target_id in e.get("metadata", {}).get(METADATA_KEY_RESOLVES, []):
            new_since["resolutions"].append(target_id)

    return new_since


def prepare_curation_data(smm_dir: Path) -> dict:
    """Prepare structured data for housekeeping curation.

    `current_smm` is loaded from shared_mental_model.json (the persistent
    store). `new_since_last_curation` is derived from events after the
    watermark. This is the commit that closes the seed-wipe regression —
    pillars no longer re-derive from events on every pass.
    """
    current_smm = smm_store.load_smm(smm_dir)

    events, _ = parse_events(smm_dir)
    if not events:
        return {
            "current_smm": current_smm,
            "new_since_last_curation": _empty_new_since(),
            "retro_history": _empty_retro_history(),
            "aging": {},
            "health": _health_from_smm(current_smm),
        }

    watermark = read_curation_watermark(smm_dir)
    wm_count = watermark["event_count"]

    # Single pass — collect the two things prepare_curation_data still needs.
    retros: list[dict] = []
    session_end_timestamps: list[str] = []
    for e in events:
        etype = e.get("type", "")
        if etype == event_schema.EVENT_TYPE_RETROSPECTIVE:
            retros.append(e)
        elif etype == event_schema.EVENT_TYPE_SESSION_END:
            session_end_timestamps.append(e.get("ts", ""))

    retro_history = _extract_retro_history(retros)

    # --- new_since_last_curation (events after watermark) ---

    new_events = events[wm_count:]
    new_resolutions = resolution.compute_resolutions(new_events)
    resolved_concern_ids = new_resolutions.get("resolved_concern_ids", set())
    new_since = _bucket_new_events(new_events, resolved_concern_ids)

    # --- annotate resolved risks (copy to avoid mutating persisted SMM) ---

    resolution_targets = set(new_since["resolutions"])
    if resolution_targets and current_smm.get("risks"):
        current_smm = {**current_smm, "risks": [dict(r) for r in current_smm["risks"]]}
        for risk in current_smm["risks"]:
            if (
                risk["id"] in resolution_targets
                or risk.get("source_event_id") in resolution_targets
            ):
                risk["resolved"] = True

    # --- aging (sessions since each risk item in current_smm) ---

    aging: dict[str, int] = {
        risk["id"]: sessions_since_event(session_end_timestamps, risk.get("ts", ""))
        for risk in current_smm.get("risks", [])
    }

    return {
        "current_smm": current_smm,
        "new_since_last_curation": new_since,
        "retro_history": retro_history,
        "aging": aging,
        "health": _health_from_smm(current_smm),
    }
