#!/usr/bin/env python3
"""Resolution tracking and notification helpers.

Extracted from _append_impl.py to reduce module size and clarify boundaries.

Two sections:
  1. Event resolution tracking (pure logic, no IO)
  2. Desktop notifications for blocking questions
"""

import re
import subprocess
import sys

import event_schema
from event_schema import METADATA_KEY_RESOLVES

# ---------------------------------------------------------------------------
# Event resolution tracking (shared by materialize, retrospective, hooks)
# ---------------------------------------------------------------------------

_ID_FULL_LENGTH = 12


def resolve_prefix(target_id: str, by_id: dict[str, dict]) -> tuple[str, dict] | None:
    """Resolve an event ID by exact match.

    With 12-char hex IDs, exact match is the primary path. Prefix
    scanning is retained as a fallback for any IDs shorter than 12 chars.
    Returns (full_id, event) or None if not found / ambiguous.
    """
    event = by_id.get(target_id)
    if event:
        return target_id, event

    if len(target_id) >= _ID_FULL_LENGTH:
        return None

    match_id: str | None = None
    for k in by_id:
        if k.startswith(target_id):
            if match_id is not None:
                return None
            match_id = k

    if match_id is not None:
        return match_id, by_id[match_id]
    return None


def compute_resolutions(events: list[dict]) -> dict:
    """Single-pass computation of question answers and event resolutions,
    followed by a one-level cascade pass.

    Resolution mechanism:
      - Questions: resolved by `answer` events that reference them,
        OR via `metadata.resolves` (answer events take precedence).
      - Goals, concerns, debt, decisions, assumptions: resolved via `metadata.resolves`
        array (any event with metadata.resolves: ["target-id"] resolves the target).
      - Cascade (WEAK): after the main pass, any event whose top-level
        `references` list contains a resolved id is itself marked resolved.
        One-level only — events closed by cascade do NOT trigger further
        cascade. Wrap in a while-changed loop to extend to multi-level.

    Returns dict with:
      - question_answers: dict mapping question event ID → answer event
      - concern_resolutions: dict mapping concern event ID → resolving event
      - goal_resolutions: dict mapping goal event ID → resolving event
      - debt_resolutions: dict mapping debt event ID → resolving event
      - decision_resolutions: dict mapping decision event ID → resolving event
      - assumption_resolutions: dict mapping assumption event ID → resolving event
      - other_resolutions: dict mapping any other event type ID → resolving event
      - answered_question_ids: set of answered question IDs
      - resolved_concern_ids: set of resolved concern IDs
      - resolved_goal_ids: set of resolved goal IDs
      - resolved_debt_ids: set of resolved debt IDs
      - resolved_decision_ids: set of resolved decision IDs
      - resolved_assumption_ids: set of resolved assumption IDs
      - resolved_other_ids: set of resolved other event IDs
    """
    by_id: dict[str, dict] = {}
    question_answers: dict[str, dict] = {}
    concern_resolutions: dict[str, dict] = {}
    goal_resolutions: dict[str, dict] = {}
    debt_resolutions: dict[str, dict] = {}
    decision_resolutions: dict[str, dict] = {}
    assumption_resolutions: dict[str, dict] = {}
    other_resolutions: dict[str, dict] = {}

    for event in events:
        event_id = event.get("id", "")
        if event_id:
            by_id[event_id] = event

        # Index nested retrospective.try[] ids so disposition events
        # (adopt/defer/drop) can resolve them via metadata.resolves.
        # Top-level event IDs (set unconditionally above) take precedence
        # on collision — setdefault preserves them.
        if event.get("type") == event_schema.EVENT_TYPE_RETROSPECTIVE:
            for item in event.get("try", []):
                if not isinstance(item, dict):
                    continue
                try_id = item.get("id")
                if not try_id:
                    continue
                by_id.setdefault(
                    try_id,
                    {
                        "id": try_id,
                        "type": "retro_try",
                        "content": item.get("content", ""),
                        "ts": event.get("ts", ""),
                        "parent_retro_id": event_id,
                    },
                )

        # Question-answer linking: answer events reference questions
        if event.get("type") == event_schema.EVENT_TYPE_ANSWER:
            for ref_id in event.get("references", []):
                ref_event = by_id.get(ref_id)
                if (
                    ref_event
                    and ref_event.get("type") == event_schema.EVENT_TYPE_QUESTION
                ):
                    question_answers[ref_id] = event

        # Explicit resolution via metadata.resolves
        for target_id in event.get("metadata", {}).get(METADATA_KEY_RESOLVES, []):
            resolved = resolve_prefix(target_id, by_id)
            if not resolved:
                continue
            full_id, target = resolved
            match target.get("type"):
                case event_schema.EVENT_TYPE_QUESTION:
                    # setdefault: answer events (added above) take
                    # precedence over metadata.resolves
                    question_answers.setdefault(full_id, event)
                case event_schema.EVENT_TYPE_CONCERN:
                    concern_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_GOAL:
                    goal_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_DEBT:
                    debt_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_DECISION:
                    decision_resolutions[full_id] = event
                case event_schema.EVENT_TYPE_ASSUMPTION:
                    assumption_resolutions[full_id] = event
                case _:
                    other_resolutions[full_id] = event

    buckets = {
        event_schema.EVENT_TYPE_QUESTION: question_answers,
        event_schema.EVENT_TYPE_CONCERN: concern_resolutions,
        event_schema.EVENT_TYPE_GOAL: goal_resolutions,
        event_schema.EVENT_TYPE_DEBT: debt_resolutions,
        event_schema.EVENT_TYPE_DECISION: decision_resolutions,
        event_schema.EVENT_TYPE_ASSUMPTION: assumption_resolutions,
    }
    resolver_map: dict[str, dict] = {}
    for bucket in (*buckets.values(), other_resolutions):
        resolver_map.update(bucket)

    for event in events:
        event_id = event.get("id")
        if not event_id or event_id in resolver_map:
            continue
        refs = event.get("references") or []
        resolver = next(
            (resolver_map[r] for r in refs if r != event_id and r in resolver_map),
            None,
        )
        if resolver is None:
            continue
        bucket = buckets.get(event.get("type", ""), other_resolutions)
        bucket.setdefault(event_id, resolver)

    return {
        "question_answers": question_answers,
        "concern_resolutions": concern_resolutions,
        "goal_resolutions": goal_resolutions,
        "debt_resolutions": debt_resolutions,
        "decision_resolutions": decision_resolutions,
        "assumption_resolutions": assumption_resolutions,
        "answered_question_ids": set(question_answers.keys()),
        "resolved_concern_ids": set(concern_resolutions.keys()),
        "resolved_goal_ids": set(goal_resolutions.keys()),
        "resolved_debt_ids": set(debt_resolutions.keys()),
        "resolved_decision_ids": set(decision_resolutions.keys()),
        "resolved_assumption_ids": set(assumption_resolutions.keys()),
        "other_resolutions": other_resolutions,
        "resolved_other_ids": set(other_resolutions.keys()),
    }


def collect_all_resolved_ids(resolutions: dict) -> set[str]:
    """Union every set value at a `*_ids` key in *resolutions*.

    Single source of truth for the "what events have been resolved at all"
    question. Co-located with `compute_resolutions` so adding a new
    `*_ids` key here keeps the helper in sync automatically — the suffix
    scan picks it up. Callers: draft_summary.py, triage_preload.py,
    concern_triage.py.
    """
    resolved: set[str] = set()
    for key, value in resolutions.items():
        if key.endswith("_ids"):
            resolved |= value
    return resolved


# ---------------------------------------------------------------------------
# Desktop notification for blocking questions
# ---------------------------------------------------------------------------


def _detect_platform() -> str:
    """Return 'macos', 'linux', or 'unknown'."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def _sanitize_notification(text: str) -> str:
    """Allow only safe characters and limit to 200 chars for shell use."""
    text = re.sub(r"[^a-zA-Z0-9 .,!?:;\-_()\n]", "", text)
    return text[:200]


def _notify_blocking_question(event: dict) -> None:
    """Send a desktop notification for 🔴 priority questions. Swallows all errors."""
    try:
        if event.get("type") != event_schema.EVENT_TYPE_QUESTION:
            return
        if event.get("priority") != event_schema.PRIORITY_BLOCKING:
            return

        message = _sanitize_notification(event.get("content", "Blocking question"))
        platform = _detect_platform()

        if platform == "macos":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "XP Agents"',
                ],
                timeout=5,
                capture_output=True,
            )
        elif platform == "linux":
            subprocess.run(
                ["notify-send", "XP Agents", message],
                timeout=5,
                capture_output=True,
            )
    except Exception:
        pass
