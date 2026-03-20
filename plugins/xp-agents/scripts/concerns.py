#!/usr/bin/env python3
"""Concern detection, conflict analysis, semantic references, and debt lookup.

Extracted from _common.py to keep modules focused on a single responsibility.
"""

import bisect
import re
import sys
from collections.abc import Callable
from pathlib import Path

# Ensure smm/ and scripts/ are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent))

from _append_impl import compute_resolutions
from _common import (
    ASSUMPTION,
    CONCERN,
    CONVENTION,
    DEBT,
    DECISION,
    DISCOVERY,
    PRIORITY_BLOCKING,
    QUESTION,
    STATUS,
    bulk_append_safe,
    make_event,
    normalize_path,
    read_events_raw,
)

# ---------------------------------------------------------------------------
# Test concern pattern (shared by bash_post_tool.py and tdd_stop_gate.py)
# ---------------------------------------------------------------------------

TEST_CONCERN_RE = re.compile(
    r"Test (?:failures? detected|run failed|command failed)", re.IGNORECASE
)

LINT_CONCERN_PREFIX = "Lint errors in "


def resolve_concerns(
    smm_dir: Path,
    matcher: Callable[[str], object],
    agent_id: str,
    label: str,
) -> None:
    """Auto-resolve unresolved concerns whose content matches *matcher*.

    *matcher* receives the event's ``content`` string; any truthy return
    means it matches (works with both ``re.search`` and ``str.startswith``).
    """
    events = read_events_raw(smm_dir)

    if not any(
        e.get("type") == CONCERN and matcher(e.get("content", "")) for e in events
    ):
        return

    resolved_ids = compute_resolutions(events)["resolved_concern_ids"]

    unresolved = [
        e
        for e in events
        if e.get("type") == CONCERN
        and e.get("id", "") not in resolved_ids
        and matcher(e.get("content", ""))
    ]
    if not unresolved:
        return

    bulk_append_safe(
        smm_dir,
        [
            make_event(
                STATUS,
                agent_id,
                f"{label}: {c['content'][:60]}",
                working_on=[],
                metadata={"resolves": [c["id"]]},
            )
            for c in unresolved
        ],
    )


# ---------------------------------------------------------------------------
# Conflict detection (shared by post_tool_use.py and subagent_stop.py)
# ---------------------------------------------------------------------------


def make_concern(content: str, severity: str, agent_id: str) -> dict:
    """Build a concern event dict."""
    return make_event(CONCERN, agent_id, content, severity=severity)


def detect_conflicts(
    events: list[dict],
    agent_id: str,
    file_path: str | None = None,
    cwd: str | None = None,
) -> list[dict]:
    """Detect structural conflicts in the event log. Returns concern event dicts.

    When file_path/cwd are None, skip pattern 1 (overlapping working_on).
    Deduplicates: skips concerns whose content already exists in the event log.
    """
    # Collect existing concern state for deduplication and escalation.
    resolutions = compute_resolutions(events)
    resolved_ids = resolutions["resolved_concern_ids"]
    existing_unresolved = {
        e.get("content", "")
        for e in events
        if e.get("type") == CONCERN and e.get("id", "") not in resolved_ids
    }
    # Count how many times each concern content was previously resolved
    # (for severity escalation on recurrence).
    resolved_content_counts: dict[str, int] = {}
    for e in events:
        if e.get("type") == CONCERN and e.get("id", "") in resolved_ids:
            content = e.get("content", "")
            resolved_content_counts[content] = (
                resolved_content_counts.get(content, 0) + 1
            )
    concerns: list[dict] = []

    def _add_concern(content: str, severity: str) -> None:
        """Append concern only if no unresolved duplicate exists.

        Escalates severity based on recurrence: each prior resolved
        instance of the same content bumps severity (low → medium → high).
        """
        if content not in existing_unresolved:
            prior_count = resolved_content_counts.get(content, 0)
            if prior_count >= 2:
                severity = "high"
            elif prior_count >= 1:
                severity = "medium"
            concerns.append(make_concern(content, severity, agent_id))
            existing_unresolved.add(content)

    # 1. Overlapping working_on — another agent claims same file
    if file_path is not None and cwd is not None:
        normalized = normalize_path(file_path, cwd)
        agent_files: dict[str, list[str]] = {}
        for e in events:
            if e.get("type") == STATUS and "working_on" in e:
                agent_files[e.get("agent_id", "")] = e["working_on"]

        for aid, files in agent_files.items():
            if aid == agent_id:
                continue
            norm_files = {normalize_path(f, cwd) for f in files}
            if normalized in norm_files:
                _add_concern(
                    f"Overlapping working_on: agent '{aid}' is also working on "
                    f"'{file_path}'. Coordinate to avoid conflicts.",
                    "medium",
                )

    # 2. Assumption contradicted by discovery
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == ASSUMPTION:
            assumptions[e.get("id", "")] = e
        elif e.get("type") == DISCOVERY:
            for ref in e.get("references", []):
                if ref in assumptions:
                    _add_concern(
                        f"Assumption contradicted: '{assumptions[ref]['content']}' "
                        f"contradicted by discovery '{e['content']}'.",
                        "high",
                    )

    # 3. Convention violation — decision diverges from convention on same topic
    conventions_by_topic: dict[str, list[dict]] = {}
    for e in events:
        if e.get("type") == CONVENTION:
            topic = e.get("topic", "")
            conventions_by_topic.setdefault(topic, []).append(e)

    for e in events:
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            if topic in conventions_by_topic:
                refs = set(e.get("references", []))
                conv_ids = {c["id"] for c in conventions_by_topic[topic]}
                if not refs & conv_ids:
                    _add_concern(
                        f"Convention violation: decision on '{topic}' "
                        "diverges from established convention.",
                        "medium",
                    )

    # 4. Stale question — blocking question with no answer after 20+ subsequent events
    question_positions: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.get("type") == QUESTION and e.get("priority") == PRIORITY_BLOCKING:
            question_positions[e.get("id", "")] = i

    answered_ids = resolutions["answered_question_ids"]

    total = len(events)
    for qid, pos in question_positions.items():
        if qid not in answered_ids and (total - pos - 1) >= 20:
            _add_concern(
                f"Stale question: blocking question (id {qid[:8]}) "
                f"has not been answered.",
                "medium",
            )

    # 5. Superseded decision — two decisions on same topic with no concern between
    decisions_by_topic: dict[str, list[tuple[int, dict]]] = {}
    concern_pos_list: list[int] = []
    for i, e in enumerate(events):
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            decisions_by_topic.setdefault(topic, []).append((i, e))
        elif e.get("type") == CONCERN:
            concern_pos_list.append(i)

    # concern_pos_list is already sorted (built in event order)
    for topic, decs in decisions_by_topic.items():
        if len(decs) < 2:
            continue
        for j in range(1, len(decs)):
            prev_pos = decs[j - 1][0]
            curr_pos = decs[j][0]
            # Binary search: any concern position in (prev_pos, curr_pos)?
            lo = bisect.bisect_right(concern_pos_list, prev_pos)
            has_concern_between = (
                lo < len(concern_pos_list) and concern_pos_list[lo] < curr_pos
            )
            if not has_concern_between:
                _add_concern(
                    f"Superseded decision: topic '{topic}' has multiple "
                    f"decisions without an intervening concern.",
                    "low",
                )

    return concerns


# ---------------------------------------------------------------------------
# Semantic reference enrichment (shared by post_tool_use.py and plan_review.py)
# ---------------------------------------------------------------------------


def _file_list_contains(paths: list, normalized_target: str, cwd: str) -> bool:
    """Check if any path in list matches normalized_target after normalization."""
    for f in paths:
        if isinstance(f, str):
            try:
                if normalize_path(f, cwd) == normalized_target:
                    return True
            except (ValueError, OSError):
                continue
    return False


def find_related_decisions(events: list[dict], file_path: str, cwd: str) -> list[str]:
    """Find event IDs of decisions/conventions that reference this file."""
    normalized = normalize_path(file_path, cwd)
    related: list[str] = []

    for e in events:
        if e.get("type") not in (DECISION, CONVENTION):
            continue
        # Check working_on field
        working_on = e.get("working_on", [])
        if isinstance(working_on, list) and _file_list_contains(
            working_on, normalized, cwd
        ):
            related.append(e["id"])
            continue
        # Check references field for normalized path matches
        refs = e.get("references", [])
        if isinstance(refs, list) and _file_list_contains(refs, normalized, cwd):
            related.append(e["id"])

    return related


# ---------------------------------------------------------------------------
# Debt lookup
# ---------------------------------------------------------------------------


def find_debt_for_file(events: list[dict], file_path: str, cwd: str) -> list[dict]:
    """Filter debt events whose files array includes the target file."""
    normalized_target = normalize_path(file_path, cwd)
    return [
        e
        for e in events
        if e.get("type") == DEBT
        and isinstance(e.get("files", []), list)
        and _file_list_contains(e["files"], normalized_target, cwd)
    ]
