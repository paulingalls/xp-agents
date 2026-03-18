#!/usr/bin/env python3
"""SMM Materializer: event parsing, index building, and curation data.

Parses the append-only event log, builds indices for lookups, and
prepares structured curation data for the housekeeping skill.
"""

import bisect
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _append_impl import (
    compute_resolutions,
)
from _append_impl import (
    read_with_lock as _read_with_lock,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curation watermark (M1)
# ---------------------------------------------------------------------------

_CURATION_WM_DEFAULTS = {"event_count": 0, "timestamp": "", "agent_id": ""}


def write_curation_watermark(smm_dir: Path, event_count: int, agent_id: str) -> None:
    """Atomic write of curation watermark via tempfile + rename."""
    from _append_impl import write_json_atomic

    wm_file = smm_dir / ".curation-watermark"
    if wm_file.is_symlink():
        raise OSError(f"Curation watermark path is a symlink: {wm_file}")

    data = {
        "event_count": event_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


def short_id(event_id: str) -> str:
    """First 8 chars of UUID for readability."""
    return event_id[:8]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_events(smm_dir: Path) -> tuple[list[dict], int]:
    """Read events.jsonl under shared flock, validate required fields.

    Uses parse_jsonl() for core JSONL parsing, then validates that each
    event has 'id' and 'type' fields.
    """
    from _append_impl import parse_jsonl

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


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def build_indices(events: list[dict]) -> dict:
    """Single-pass grouping of events into lookup structures."""
    indices: dict = {
        "by_type": defaultdict(list),
        "by_id": {},
        "event_positions": {},
        "latest_status": {},
        "question_answers": {},
        "question_assumptions": {},
        "decisions_by_topic": defaultdict(list),
        "conventions_by_topic": defaultdict(list),
        "assumption_contradictions": {},
        "agent_ids": set(),
        "session_end_positions": [],
        "last_session_end_pos": -1,
        "intent_by_status": defaultdict(list),
    }

    for i, event in enumerate(events):
        event_type = event.get("type", "")
        event_id = event.get("id", "")

        indices["by_type"][event_type].append(event)
        agent_id = event.get("agent_id", "")
        if agent_id:
            indices["agent_ids"].add(agent_id)
        if event_id:
            indices["by_id"][event_id] = event
            indices["event_positions"][event_id] = i

        match event_type:
            case "status":
                indices["latest_status"][event.get("agent_id", "")] = event

            case "session_end":
                indices["session_end_positions"].append((i, event.get("ts", "")))
                indices["last_session_end_pos"] = i

            case "customer_intent":
                intent_status = event.get("intent_status", "")
                if intent_status:
                    indices["intent_by_status"][intent_status].append(event)

            case "decision":
                topic = event.get("topic", "")
                if topic:
                    indices["decisions_by_topic"][topic].append(event)

            case "convention":
                topic = event.get("topic", "")
                if topic:
                    indices["conventions_by_topic"][topic].append(event)

            case "assumption":
                for ref_id in event.get("references", []):
                    ref_event = indices["by_id"].get(ref_id)
                    if ref_event and ref_event.get("type") == "question":
                        indices["question_assumptions"][ref_id] = event

            case "discovery":
                for ref_id in event.get("references", []):
                    ref_event = indices["by_id"].get(ref_id)
                    if ref_event and ref_event.get("type") == "assumption":
                        indices["assumption_contradictions"][ref_id] = event

    # Resolution tracking via shared utility
    resolutions = compute_resolutions(events)
    indices["question_answers"] = resolutions["question_answers"]
    indices["concern_resolutions"] = resolutions["concern_resolutions"]
    indices["goal_resolutions"] = resolutions["goal_resolutions"]
    indices["debt_resolutions"] = resolutions["debt_resolutions"]
    indices["decision_resolutions"] = resolutions["decision_resolutions"]

    return indices


def _extract_retro_history(retro_events: list[dict]) -> dict:
    """Extract retrospective history from retrospective events.

    Args:
        retro_events: Pre-filtered list of retrospective events
            (from indices["by_type"]["retrospective"]).

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
        "adopted_tries": adopted_tries,
    }


def prepare_curation_data(smm_dir: Path) -> dict:
    """Prepare structured data for housekeeping curation.

    Reuses parse_events() and build_indices() to extract four-pillar
    data from the event log. Returns a dict matching the schema in
    docs/SMM_DESIGN.md.
    """
    events, _ = parse_events(smm_dir)
    if not events:
        return {
            "current_smm": {
                "intent": [],
                "constraints": [],
                "risks": [],
                "wisdom": [],
            },
            "new_since_last_curation": {
                "customer_inputs": [],
                "decisions": [],
                "concerns": [],
                "assumptions": [],
                "debt": [],
                "questions": [],
                "resolutions": {},
            },
            "retro_history": {
                "latest_tries": [],
                "recurring_fixes": [],
                "adopted_tries": [],
            },
            "aging": {},
            "health": {
                "intent_count": 0,
                "constraints_count": 0,
                "risks_count": 0,
                "wisdom_count": 0,
            },
        }

    indices = build_indices(events)
    watermark = read_curation_watermark(smm_dir)
    wm_count = watermark["event_count"]

    # --- current_smm (derived from ALL events) ---

    # Intent: unresolved goals + open customer_intents
    goal_resolutions = indices["goal_resolutions"]
    intent_items: list[dict] = []
    for g in indices["by_type"].get("goal", []):
        if g["id"] not in goal_resolutions:
            intent_items.append(
                {"id": g["id"], "content": g.get("content", ""), "type": "goal"}
            )
    for ci in indices["intent_by_status"].get("open", []):
        intent_items.append(
            {
                "id": ci["id"],
                "content": ci.get("content", ""),
                "type": "customer_intent",
            }
        )

    # Constraints: non-draft unresolved decisions + conventions
    decision_resolutions = indices["decision_resolutions"]
    constraint_items: list[dict] = []
    for d in indices["by_type"].get("decision", []):
        if d["id"] in decision_resolutions:
            continue
        if d.get("metadata", {}).get("draft"):
            continue
        constraint_items.append(
            {
                "id": d["id"],
                "content": d.get("content", ""),
                "topic": d.get("topic", ""),
                "type": "decision",
            }
        )
    for c in indices["by_type"].get("convention", []):
        constraint_items.append(
            {
                "id": c["id"],
                "content": c.get("content", ""),
                "topic": c.get("topic", ""),
                "type": "convention",
            }
        )

    # Risks: unresolved concerns + unverified assumptions + unresolved debt
    #         + unanswered questions
    concern_resolutions = indices["concern_resolutions"]
    debt_resolutions = indices["debt_resolutions"]
    risk_items: list[dict] = []
    for c in indices["by_type"].get("concern", []):
        if c["id"] not in concern_resolutions:
            risk_items.append(
                {
                    "id": c["id"],
                    "content": c.get("content", ""),
                    "severity": "problem",
                    "type": "concern",
                }
            )
    for a in indices["by_type"].get("assumption", []):
        if a["id"] not in indices["assumption_contradictions"]:
            risk_items.append(
                {
                    "id": a["id"],
                    "content": a.get("content", ""),
                    "severity": "uncertainty",
                    "type": "assumption",
                }
            )
    for d in indices["by_type"].get("debt", []):
        if d["id"] not in debt_resolutions:
            risk_items.append(
                {
                    "id": d["id"],
                    "content": d.get("content", ""),
                    "severity": "debt",
                    "type": "debt",
                }
            )
    for q in indices["by_type"].get("question", []):
        if (
            q["id"] not in indices["question_answers"]
            and q["id"] not in indices["question_assumptions"]
        ):
            risk_items.append(
                {
                    "id": q["id"],
                    "content": q.get("content", ""),
                    "severity": "uncertainty",
                    "type": "question",
                }
            )

    # Wisdom: populated from retro_history
    retro_history = _extract_retro_history(indices["by_type"].get("retrospective", []))
    wisdom_items = [
        {"content": t, "type": "adopted_try"} for t in retro_history["adopted_tries"]
    ]

    current_smm = {
        "intent": intent_items,
        "constraints": constraint_items,
        "risks": risk_items,
        "wisdom": wisdom_items,
    }

    # --- new_since_last_curation (events after watermark) ---

    new_events = events[wm_count:]
    new_since: dict = {
        "customer_inputs": [],
        "decisions": [],
        "concerns": [],
        "assumptions": [],
        "debt": [],
        "questions": [],
        "resolutions": {},
    }
    for e in new_events:
        etype = e.get("type", "")
        summary = {
            "id": e.get("id", ""),
            "content": e.get("content", ""),
            "ts": e.get("ts", ""),
            "agent_id": e.get("agent_id", ""),
        }
        match etype:
            case "customer_input":
                new_since["customer_inputs"].append(summary)
            case "decision":
                summary["topic"] = e.get("topic", "")
                summary["draft"] = bool(e.get("metadata", {}).get("draft"))
                new_since["decisions"].append(summary)
            case "concern":
                new_since["concerns"].append(summary)
            case "assumption":
                new_since["assumptions"].append(summary)
            case "debt":
                summary["files"] = e.get("files", [])
                new_since["debt"].append(summary)
            case "question":
                summary["priority"] = e.get("priority", "")
                new_since["questions"].append(summary)

        # Track resolutions in new events
        resolves = e.get("metadata", {}).get("resolves", [])
        for target_id in resolves:
            new_since["resolutions"][target_id] = e.get("content", "")

    # --- aging (sessions since each risk item) ---

    se_timestamps = [ts for _, ts in indices["session_end_positions"]]
    aging: dict[str, int] = {}
    for risk in risk_items:
        risk_id = risk["id"]
        risk_event = indices["by_id"].get(risk_id)
        if risk_event:
            risk_ts = risk_event.get("ts", "")
            sessions_after = len(se_timestamps) - bisect.bisect_right(
                se_timestamps, risk_ts
            )
            aging[risk_id] = sessions_after

    # --- health ---

    health = {
        "intent_count": len(intent_items),
        "constraints_count": len(constraint_items),
        "risks_count": len(risk_items),
        "wisdom_count": len(wisdom_items),
    }

    return {
        "current_smm": current_smm,
        "new_since_last_curation": new_since,
        "retro_history": retro_history,
        "aging": aging,
        "health": health,
    }
