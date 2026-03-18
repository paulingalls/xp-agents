#!/usr/bin/env python3
"""SMM Materializer: events.jsonl → SHARED_MENTAL_MODEL.md

Parses the append-only event log, builds indices, detects structural
conflicts, and renders a human-readable markdown view. Atomic write
via tempfile + os.rename.
"""

import argparse
import bisect
import contextlib
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
from _append_impl import (
    PRIORITY_BLOCKING,
    LockTimeoutError,
    _validate_smm_dir,
    compute_resolutions,
    resolve_smm_dir,
)
from _append_impl import (
    VALID_TYPES as _VALID_TYPES_LIST,
)
from _append_impl import (
    read_with_lock as _read_with_lock,
)

STALE_THRESHOLD = 50
VALID_TYPES = frozenset(_VALID_TYPES_LIST)


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
    """Read events.jsonl under shared flock, skip malformed lines."""
    raw = _read_with_lock(smm_dir / "events.jsonl")
    if not raw.strip():
        return [], 0

    events: list[dict] = []
    skipped = 0

    for line_num, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                print(
                    f"Warning: Line {line_num} is not a JSON object, skipping",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            if "id" not in event or "type" not in event:
                print(
                    f"Warning: Line {line_num} missing id or type, skipping",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            events.append(event)
        except json.JSONDecodeError:
            print(
                f"Warning: Line {line_num} is malformed JSON, skipping",
                file=sys.stderr,
            )
            skipped += 1

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


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_conflicts(events: list[dict], indices: dict) -> list[str]:
    """Detect 5 structural conflict patterns."""
    conflicts: list[str] = []
    positions = indices["event_positions"]

    # 1. Overlapping working_on
    latest = indices["latest_status"]
    agents = sorted(latest.keys())
    for i, agent_a in enumerate(agents):
        files_a = set(latest[agent_a].get("working_on", []))
        if not files_a:
            continue
        for agent_b in agents[i + 1 :]:
            files_b = set(latest[agent_b].get("working_on", []))
            for f in sorted(files_a & files_b):
                conflicts.append(
                    f"⚠️ working_on overlap: {agent_a} and {agent_b} both claim {f}"
                )

    # 2. Assumption contradicted by discovery
    for assumption_id in sorted(indices["assumption_contradictions"]):
        discovery = indices["assumption_contradictions"][assumption_id]
        conflicts.append(
            f"⚠️ assumption contradicted: {short_id(assumption_id)} "
            f"contradicted by {short_id(discovery['id'])}"
        )

    # 3. Convention violation — decision shares topic but doesn't reference it
    for topic in sorted(indices["decisions_by_topic"]):
        conventions = indices["conventions_by_topic"].get(topic, [])
        if not conventions:
            continue
        convention_ids = {c["id"] for c in conventions}
        for decision in indices["decisions_by_topic"][topic]:
            decision_refs = set(decision.get("references", []))
            if not (decision_refs & convention_ids):
                conv_id = conventions[-1]["id"]
                conflicts.append(
                    f"⚠️ convention violation: decision {short_id(decision['id'])} "
                    f"diverges from convention {short_id(conv_id)}"
                )

    # 4. Stale question — 🔴 with no answer after STALE_THRESHOLD events
    for q in indices["by_type"].get("question", []):
        if q.get("priority") != PRIORITY_BLOCKING:
            continue
        q_id = q["id"]
        if q_id in indices["question_answers"]:
            continue
        q_pos = positions.get(q_id, -1)
        if q_pos >= 0:
            events_since = len(events) - q_pos - 1
            if events_since >= STALE_THRESHOLD:
                conflicts.append(
                    f"⚠️ stale question: {short_id(q_id)} has had no answer "
                    f"for {events_since} events"
                )

    # 5. Superseded decision — same topic, no concern referencing either between
    for topic in sorted(indices["decisions_by_topic"]):
        decisions = indices["decisions_by_topic"][topic]
        if len(decisions) < 2:
            continue
        for j in range(len(decisions) - 1):
            d1 = decisions[j]
            d2 = decisions[j + 1]
            d1_id, d2_id = d1["id"], d2["id"]
            d1_pos = positions.get(d1_id, -1)
            d2_pos = positions.get(d2_id, -1)
            if d1_pos < 0 or d2_pos < 0:
                continue
            has_concern_between = False
            for k in range(d1_pos + 1, d2_pos):
                e = events[k]
                if e.get("type") == "concern":
                    refs = set(e.get("references", []))
                    if d1_id in refs or d2_id in refs:
                        has_concern_between = True
                        break
            if not has_concern_between:
                conflicts.append(
                    f"⚠️ superseded decision: {short_id(d2_id)} supersedes "
                    f"{short_id(d1_id)} on topic '{topic}' with no concern raised"
                )

    return conflicts


# ---------------------------------------------------------------------------
# Drift signal detection
# ---------------------------------------------------------------------------

STALE_SESSIONS_THRESHOLD = 5
IGNORED_CONVENTION_THRESHOLD = 3


def detect_drift_signals(events: list[dict], indices: dict) -> list[str]:
    """Detect drift signals from the event log only (no codebase I/O).

    Signal types:
    - Stale decision: topic with no related events in 5+ sessions
    - Ignored convention: topic with 3+ unresolved concerns referencing it
    """
    signals: list[str] = []

    # Session end positions for staleness detection
    session_end_positions = indices["session_end_positions"]
    total_sessions = len(session_end_positions)

    # 1. Stale decisions — topic with no related events in 5+ sessions
    if total_sessions >= STALE_SESSIONS_THRESHOLD:
        # Pre-extract position list for bisect (O(S) once, not per topic)
        se_pos_list = [pos for pos, _ in session_end_positions]

        decision_resolutions = indices["decision_resolutions"]
        for topic in sorted(indices["decisions_by_topic"]):
            decisions = indices["decisions_by_topic"][topic]
            # Skip topics where all decisions are resolved
            if all(d.get("id", "") in decision_resolutions for d in decisions):
                continue
            # Find latest event position for this topic (any type)
            latest_pos = -1
            for d in decisions:
                pos = indices["event_positions"].get(d.get("id", ""), -1)
                if pos > latest_pos:
                    latest_pos = pos
            # Also check conventions on the same topic
            for c in indices["conventions_by_topic"].get(topic, []):
                pos = indices["event_positions"].get(c.get("id", ""), -1)
                if pos > latest_pos:
                    latest_pos = pos

            if latest_pos < 0:
                continue

            # Count session_ends after latest activity via bisect (O(log S))
            sessions_since = total_sessions - bisect.bisect_right(
                se_pos_list, latest_pos
            )

            if sessions_since >= STALE_SESSIONS_THRESHOLD:
                signals.append(
                    f"⚠️ Stale decision: topic '{topic}' has had no related "
                    f"events for {sessions_since} sessions"
                )

    # 2. Ignored conventions — 3+ unresolved concerns referencing convention
    concern_resolutions = indices["concern_resolutions"]

    # Build reverse index: convention_id → topic (O(1) lookup per reference)
    conv_id_to_topic: dict[str, str] = {}
    for topic, convs in indices["conventions_by_topic"].items():
        for c in convs:
            conv_id_to_topic[c["id"]] = topic

    # Count unresolved concerns per convention topic
    convention_concern_counts: dict[str, int] = defaultdict(int)
    for concern in indices["by_type"].get("concern", []):
        if concern["id"] in concern_resolutions:
            continue  # resolved
        for ref_id in concern.get("references", []):
            topic = conv_id_to_topic.get(ref_id)
            if topic:
                convention_concern_counts[topic] += 1

    for topic in sorted(convention_concern_counts):
        count = convention_concern_counts[topic]
        if count >= IGNORED_CONVENTION_THRESHOLD:
            signals.append(
                f"⚠️ Ignored convention: topic '{topic}' has {count} unresolved concerns"
            )

    return signals


# ---------------------------------------------------------------------------
# Velocity metrics
# ---------------------------------------------------------------------------


def compute_velocity(events: list[dict], indices: dict) -> dict:
    """Compute velocity metrics from the event log.

    Returns dict with: events_this_session, total_sessions, decisions_made,
    decisions_revisited, churn_topics, concerns_total, concerns_resolved.
    """
    # Events this session (since last session_end)
    last_se_pos = indices["last_session_end_pos"]
    events_this_session = (
        len(events) - last_se_pos - 1 if last_se_pos >= 0 else len(events)
    )

    # Total sessions
    total_sessions = len(indices["session_end_positions"])

    # Decisions
    decisions_made = len(indices["by_type"].get("decision", []))
    decisions_revisited = sum(
        1 for decisions in indices["decisions_by_topic"].values() if len(decisions) >= 2
    )

    # Churn topics (3+ decisions on same topic)
    churn_topics = sorted(
        topic
        for topic, decisions in indices["decisions_by_topic"].items()
        if len(decisions) >= 3
    )

    # Concern resolution
    concerns = indices["by_type"].get("concern", [])
    concerns_total = len(concerns)
    concerns_resolved = sum(
        1 for c in concerns if c["id"] in indices["concern_resolutions"]
    )

    return {
        "events_this_session": events_this_session,
        "total_sessions": total_sessions,
        "decisions_made": decisions_made,
        "decisions_revisited": decisions_revisited,
        "churn_topics": churn_topics,
        "concerns_total": concerns_total,
        "concerns_resolved": concerns_resolved,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(
    events: list[dict],
    indices: dict,
    conflicts: list[str],
    skipped: int,
) -> str:
    """Render the SHARED_MENTAL_MODEL.md content.

    Two-tier structure: ACTIVE CONTEXT (actionable) and REFERENCE (background).
    """

    sections: list[str] = []

    agent_count = len(indices["agent_ids"])

    # Header
    header = (
        f"# Shared Mental Model\n"
        f"*Auto-generated from events.jsonl "
        f"({len(events)} events, {agent_count} agents)*"
    )
    if skipped > 0:
        header += f"\n*⚠️ {skipped} malformed lines skipped*"
    sections.append(header)

    # ===================================================================
    # ACTIVE CONTEXT
    # ===================================================================
    active_sections: list[str] = []

    # A1. Project Goals — only unresolved
    goals = indices["by_type"].get("goal", [])
    active_goals = [g for g in goals if g["id"] not in indices["goal_resolutions"]]
    if active_goals:
        lines = ["## Project Goals"]
        for g in active_goals:
            lines.append(
                f"- 🎯 {g.get('content', '')} "
                f"[{g.get('agent_id', '')}, {short_id(g.get('id', ''))}]"
            )
        active_sections.append("\n".join(lines))

    # A2. Conflict Alerts
    if conflicts:
        lines = ["## Conflict Alerts"]
        lines.extend(f"- {c}" for c in conflicts)
        active_sections.append("\n".join(lines))

    # A3. Blocking Questions — only 🔴 unanswered/unassumed
    questions = indices["by_type"].get("question", [])
    blocking_qs = [
        q
        for q in questions
        if q.get("priority") == PRIORITY_BLOCKING
        and q["id"] not in indices["question_answers"]
        and q["id"] not in indices["question_assumptions"]
    ]
    if blocking_qs:
        lines = ["## Blocking Questions"]
        for q in blocking_qs:
            q_id = q["id"]
            lines.append(
                f"- 🔴 {q.get('content', '')} "
                f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                f"— **blocking, awaiting answer**"
            )
        active_sections.append("\n".join(lines))

    # A4. Unacknowledged Concerns
    concerns = indices["by_type"].get("concern", [])
    unack_concerns = [
        c for c in concerns if c["id"] not in indices["concern_resolutions"]
    ]
    if unack_concerns:
        lines = ["## Unacknowledged Concerns"]
        for c in unack_concerns:
            content = c.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(
                f"- ⚠️ {content} "
                f"[{c.get('agent_id', '')}, {short_id(c['id'])}] "
                f"— unacknowledged"
            )
        active_sections.append("\n".join(lines))

    # A5. Customer Intent — open items only
    open_intents = indices["intent_by_status"].get("open", [])
    if open_intents:
        lines = ["## Customer Intent"]
        for ci in open_intents:
            refs_str = ""
            if ci.get("references"):
                ref_parts = [short_id(r) for r in ci["references"]]
                refs_str = f" (refs: {', '.join(ref_parts)})"
            lines.append(
                f"- 📋 {ci.get('content', '')} "
                f"[{ci.get('agent_id', '')}, {short_id(ci.get('id', ''))}]"
                f"{refs_str}"
            )
        active_sections.append("\n".join(lines))

    # A6. Agent Status — scoped to current session
    latest = indices["latest_status"]
    last_se_pos = indices["last_session_end_pos"]
    if latest:
        lines = ["## Agent Status"]
        for agent_id in sorted(latest):
            status = latest[agent_id]
            # Skip agents whose latest status is from a prior session
            if last_se_pos >= 0:
                status_pos = indices["event_positions"].get(status.get("id", ""), -1)
                if status_pos <= last_se_pos:
                    continue
            working_on = status.get("working_on", [])
            content = status.get("content", "")
            if working_on:
                files = ", ".join(working_on)
                lines.append(f"- **{agent_id}**: {content}. Working on: {files}")
            else:
                lines.append(f"- **{agent_id}**: {content}. Idle.")
        if len(lines) > 1:  # Only emit if there are agents beyond header
            active_sections.append("\n".join(lines))

    # A8. Drift Signals
    drift_signals = detect_drift_signals(events, indices)
    if drift_signals:
        lines = ["## Drift Signals"]
        lines.extend(f"- {s}" for s in drift_signals)
        active_sections.append("\n".join(lines))

    # A9. Velocity
    velocity = compute_velocity(events, indices)
    vel_lines = ["## Velocity"]
    vel_lines.append(f"- {velocity['events_this_session']} events this session")
    vel_lines.append(f"- {velocity['total_sessions']} total sessions")
    vel_lines.append(
        f"- {velocity['decisions_made']} decisions made, "
        f"{velocity['decisions_revisited']} revisited"
    )
    if velocity["churn_topics"]:
        topics_str = ", ".join(velocity["churn_topics"])
        vel_lines.append(f"- **Churn topics**: {topics_str}")
    if velocity["concerns_total"] > 0:
        ratio = velocity["concerns_resolved"] / velocity["concerns_total"]
        vel_lines.append(
            f"- Concern resolution: {velocity['concerns_resolved']}/"
            f"{velocity['concerns_total']} ({ratio:.0%})"
        )
    active_sections.append("\n".join(vel_lines))

    # Emit Active Context
    if active_sections:
        sections.append("---\n## ACTIVE CONTEXT")
        sections.extend(active_sections)

    # ===================================================================
    # REFERENCE
    # ===================================================================
    ref_sections: list[str] = []

    # R1. Architecture Decisions — exclude resolved
    all_decisions = indices["by_type"].get("decision", [])
    decisions = [
        d for d in all_decisions if d["id"] not in indices["decision_resolutions"]
    ]
    if decisions:
        lines = ["## Architecture Decisions"]
        for d in decisions:
            prefix = "(draft) " if d.get("metadata", {}).get("draft") else ""
            refs_str = ""
            if d.get("references"):
                ref_parts = [short_id(r) for r in d["references"]]
                refs_str = f", references {', '.join(ref_parts)}"
            lines.append(
                f"- {prefix}**{d.get('content', '')}** "
                f"[{d.get('agent_id', '')}, {short_id(d.get('id', ''))}{refs_str}]"
            )
        ref_sections.append("\n".join(lines))

    # R2. Conventions
    conventions = indices["by_type"].get("convention", [])
    if conventions:
        lines = ["## Conventions"]
        for c in conventions:
            lines.append(
                f"- {c.get('content', '')} "
                f"[{c.get('agent_id', '')}, {short_id(c.get('id', ''))}]"
            )
        ref_sections.append("\n".join(lines))

    # R3. Questions (Resolved & Assumed) — answered + assumed questions
    resolved_qs = [
        q
        for q in questions
        if q["id"] in indices["question_answers"]
        or q["id"] in indices["question_assumptions"]
    ]
    if resolved_qs:
        lines = ["## Questions (Resolved & Assumed)"]
        for q in resolved_qs:
            q_id = q["id"]
            if q_id in indices["question_answers"]:
                answer = indices["question_answers"][q_id]
                lines.append(
                    f"- ✅ {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                    f"— answered: {answer.get('content', '')} "
                    f"[{short_id(answer['id'])}]"
                )
            elif q_id in indices["question_assumptions"]:
                assumption = indices["question_assumptions"][q_id]
                lines.append(
                    f"- 🟡 {q.get('content', '')} "
                    f"[{q.get('agent_id', '')}, {short_id(q_id)}] "
                    f"— **assumed: {assumption.get('content', '')}**"
                )
        ref_sections.append("\n".join(lines))

    # R4. Discoveries
    discoveries = indices["by_type"].get("discovery", [])
    if discoveries:
        lines = ["## Discoveries"]
        for d in discoveries:
            lines.append(
                f"- ⚠️ {d.get('content', '')} "
                f"[{d.get('agent_id', '')}, {short_id(d.get('id', ''))}]"
            )
        ref_sections.append("\n".join(lines))

    # R5. Assumptions
    assumptions = indices["by_type"].get("assumption", [])
    if assumptions:
        lines = ["## Assumptions"]
        for a in assumptions:
            a_id = a["id"]
            if a_id in indices["assumption_contradictions"]:
                disc = indices["assumption_contradictions"][a_id]
                lines.append(
                    f"- ❌ {a.get('content', '')} "
                    f"[{a.get('agent_id', '')}, {short_id(a_id)}] "
                    f"— contradicted by {short_id(disc['id'])}"
                )
            else:
                lines.append(
                    f"- {a.get('content', '')} "
                    f"[{a.get('agent_id', '')}, {short_id(a_id)}] "
                    f"— unverified"
                )
        ref_sections.append("\n".join(lines))

    # R6. Technical Debt — only open debt, with aging markers
    debts = indices["by_type"].get("debt", [])
    open_debts = [d for d in debts if d["id"] not in indices["debt_resolutions"]]
    if open_debts:
        # Build sorted list of session_end timestamps for bisect
        se_timestamps = [ts for _, ts in indices["session_end_positions"]]
        lines = ["## Technical Debt"]
        for d in open_debts:
            debt_ts = d.get("ts", "")
            # Count session_ends after this debt: total - those at or before debt_ts
            sessions_after = len(se_timestamps) - bisect.bisect_right(
                se_timestamps, debt_ts
            )
            if sessions_after >= 7:
                age_marker = "🔴 "
            elif sessions_after >= 4:
                age_marker = "⚠️ "
            else:
                age_marker = ""
            files = ", ".join(d.get("files", []))
            lines.append(
                f"- {age_marker}{d.get('content', '')} "
                f"[{d.get('agent_id', '')}, {short_id(d.get('id', ''))}] "
                f"(files: {files})"
            )
        ref_sections.append("\n".join(lines))

    # R7. Resolved Concerns (summary only — detail in event log)
    resolved_concern_count = sum(
        1 for c in concerns if c["id"] in indices["concern_resolutions"]
    )
    if resolved_concern_count:
        ref_sections.append(
            f"## Resolved Concerns\n"
            f"{resolved_concern_count} concern(s) resolved. "
            f"See event log for details."
        )

    # R8. Completed Goals
    completed_goals = [g for g in goals if g["id"] in indices["goal_resolutions"]]
    if completed_goals:
        lines = ["## Completed Goals"]
        for g in completed_goals:
            resolver = indices["goal_resolutions"][g["id"]]
            lines.append(
                f"- ✅ {g.get('content', '')} "
                f"[{g.get('agent_id', '')}, {short_id(g['id'])}] "
                f"— completed → {short_id(resolver['id'])}"
            )
        ref_sections.append("\n".join(lines))

    # Emit Reference
    if ref_sections:
        sections.append("---\n## REFERENCE")
        sections.extend(ref_sections)

    # Unknown Events (after both tiers)
    unknown_types = set(indices["by_type"].keys()) - VALID_TYPES
    if unknown_types:
        lines = ["## Unknown Events"]
        for ut in sorted(unknown_types):
            for e in indices["by_type"][ut]:
                lines.append(
                    f"- [{ut}] {e.get('content', '')} "
                    f"[{e.get('agent_id', '')}, {short_id(e.get('id', ''))}]"
                )
        sections.append("\n".join(lines))

    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


def extract_active_context(md_text: str) -> str:
    """Extract Active Context section (everything before REFERENCE).

    Returns the header + active context sections, or empty string if absent.
    """
    if not md_text:
        return ""

    separator = "---\n## REFERENCE"
    idx = md_text.find(separator)
    if idx >= 0:
        return md_text[:idx].rstrip() + "\n"
    # No reference section — if there's active context, return everything
    if "## ACTIVE CONTEXT" in md_text:
        return md_text
    return ""


def materialize(smm_dir: Path) -> str:
    """Parse events, build indices, detect conflicts, render markdown."""
    events, skipped = parse_events(smm_dir)
    if not events and skipped == 0:
        return ""

    indices = build_indices(events)
    conflicts = detect_conflicts(events, indices)
    return render_markdown(events, indices, conflicts, skipped)


def materialize_to_file(smm_dir: Path) -> Path:
    """Atomic write of SHARED_MENTAL_MODEL.md via tempfile + rename."""
    md = materialize(smm_dir)
    target = smm_dir / "SHARED_MENTAL_MODEL.md"

    fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(md)
        os.chmod(tmp, 0o600)
        os.rename(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize events.jsonl into SHARED_MENTAL_MODEL.md"
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
        path = materialize_to_file(smm_dir)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Materialized to {path}")


if __name__ == "__main__":
    main()
