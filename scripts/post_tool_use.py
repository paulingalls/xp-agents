#!/usr/bin/env python3
"""PostToolUse command hook: auto-status, conflict detection, semantic enrichment.

Fires after Write/Edit/MultiEdit. Records what happened, detects structural
conflicts (log-only, never blocks), and enriches status with semantic references.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_conflicts(
    events: list[dict], agent_id: str, file_path: str, cwd: str
) -> list[dict]:
    """Detect structural conflicts in the event log. Returns concern event dicts."""
    concerns: list[dict] = []
    normalized = _common.normalize_path(file_path, cwd)

    # 1. Overlapping working_on — another agent claims same file
    agent_files: dict[str, list[str]] = {}
    for e in events:
        if e.get("type") == "status" and e.get("working_on"):
            agent_files[e.get("agent_id", "")] = e["working_on"]

    for aid, files in agent_files.items():
        if aid == agent_id:
            continue
        norm_files = {_common.normalize_path(f, cwd) for f in files}
        if normalized in norm_files:
            concerns.append(
                _make_concern(
                    f"Overlapping working_on: agent '{aid}' is also working on "
                    f"'{file_path}'. Coordinate to avoid conflicts.",
                    "medium",
                    agent_id,
                )
            )

    # 2. Assumption contradicted by discovery
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == "assumption":
            assumptions[e.get("id", "")] = e
        elif e.get("type") == "discovery":
            for ref in e.get("references", []):
                if ref in assumptions:
                    concerns.append(
                        _make_concern(
                            f"Assumption contradicted: '{assumptions[ref]['content']}' "
                            f"contradicted by discovery '{e['content']}'.",
                            "high",
                            agent_id,
                        )
                    )

    # 3. Convention violation — decision diverges from convention on same topic
    conventions_by_topic: dict[str, list[dict]] = {}
    for e in events:
        if e.get("type") == "convention":
            topic = e.get("topic", "")
            conventions_by_topic.setdefault(topic, []).append(e)

    for e in events:
        if e.get("type") == "decision":
            topic = e.get("topic", "")
            if topic in conventions_by_topic:
                # Check if the decision references the convention (explicit override)
                refs = set(e.get("references", []))
                conv_ids = {c["id"] for c in conventions_by_topic[topic]}
                if not refs & conv_ids:
                    concerns.append(
                        _make_concern(
                            f"Convention violation: decision on '{topic}' "
                            "diverges from established convention.",
                            "medium",
                            agent_id,
                        )
                    )

    # 4. Stale question — 🔴 question with no answer after 20+ subsequent events
    question_positions: dict[str, int] = {}
    answered_ids: set[str] = set()
    for i, e in enumerate(events):
        if e.get("type") == "question" and e.get("priority") == "\U0001f534":
            question_positions[e.get("id", "")] = i
        elif e.get("type") == "answer":
            for ref in e.get("references", []):
                answered_ids.add(ref)

    total = len(events)
    for qid, pos in question_positions.items():
        if qid not in answered_ids and (total - pos - 1) >= 20:
            concerns.append(
                _make_concern(
                    f"Stale question: blocking question (id {qid[:8]}) has had "
                    f"{total - pos - 1} events without an answer.",
                    "medium",
                    agent_id,
                )
            )

    # 5. Superseded decision — two decisions on same topic with no concern between
    decisions_by_topic: dict[str, list[tuple[int, dict]]] = {}
    concern_positions: set[int] = set()
    for i, e in enumerate(events):
        if e.get("type") == "decision":
            topic = e.get("topic", "")
            decisions_by_topic.setdefault(topic, []).append((i, e))
        elif e.get("type") == "concern":
            concern_positions.add(i)

    for topic, decs in decisions_by_topic.items():
        if len(decs) < 2:
            continue
        for j in range(1, len(decs)):
            prev_pos = decs[j - 1][0]
            curr_pos = decs[j][0]
            has_concern_between = any(
                prev_pos < cp < curr_pos for cp in concern_positions
            )
            if not has_concern_between:
                concerns.append(
                    _make_concern(
                        f"Superseded decision: topic '{topic}' has multiple decisions "
                        f"without an intervening concern.",
                        "low",
                        agent_id,
                    )
                )

    return concerns


def _make_concern(content: str, severity: str, agent_id: str) -> dict:
    """Build a concern event dict."""
    return _common.make_event("concern", agent_id, content, severity=severity)


# ---------------------------------------------------------------------------
# Semantic reference enrichment
# ---------------------------------------------------------------------------


def find_related_decisions(events: list[dict], file_path: str, cwd: str) -> list[str]:
    """Find event IDs of decisions/conventions that reference this file."""
    normalized = _common.normalize_path(file_path, cwd)
    related: list[str] = []

    for e in events:
        if e.get("type") not in ("decision", "convention"):
            continue
        # Check working_on field
        working_on = e.get("working_on", [])
        if isinstance(working_on, list):
            norm_wo = {_common.normalize_path(f, cwd) for f in working_on}
            if normalized in norm_wo:
                related.append(e["id"])
                continue
        # Check references field for file mentions
        refs = e.get("references", [])
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, str) and file_path in ref:
                    related.append(e["id"])
                    break

    return related


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core PostToolUse logic. Appends events, never produces stdout."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = input_data.get("agent_id", "main")
    cwd = input_data.get("cwd", ".")

    file_path = _common.extract_file_path(tool_name, tool_input)
    if not file_path:
        return None

    normalized = _common.normalize_path(file_path, cwd)

    # Read events for conflict detection and semantic enrichment
    events = _common.read_events_raw(smm_dir)

    # Semantic references
    refs = find_related_decisions(events, file_path, cwd)

    # Auto-status event
    extra: dict = {"working_on": [normalized]}
    if refs:
        extra["references"] = refs
    status_event = _common.make_event(
        "status",
        agent_id,
        f"Wrote to {normalized}",
        **extra,
    )
    _common.append_safe(smm_dir, status_event)

    # Conflict detection — log-only, never exit 2
    concern_events = detect_conflicts(events, agent_id, file_path, cwd)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
