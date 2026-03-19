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

# ---------------------------------------------------------------------------
# Event resolution tracking (shared by materialize, retrospective, hooks)
# ---------------------------------------------------------------------------

_UUID_FULL_LENGTH = 36  # Standard UUID: 8-4-4-4-12 with hyphens


def resolve_prefix(target_id: str, by_id: dict[str, dict]) -> tuple[str, dict] | None:
    """Resolve an event ID, supporting short-prefix fallback.

    If target_id is a full UUID, does an O(1) dict lookup. If it's shorter
    (e.g. 8-char prefix from materialized output), scans keys for a unique
    prefix match. Returns (full_id, event) or None if not found / ambiguous.
    """
    event = by_id.get(target_id)
    if event:
        return target_id, event

    if len(target_id) >= _UUID_FULL_LENGTH:
        return None

    match_id: str | None = None
    for k in by_id:
        if k.startswith(target_id):
            if match_id is not None:
                return None  # Ambiguous — two or more matches
            match_id = k

    if match_id is not None:
        return match_id, by_id[match_id]
    return None


def compute_resolutions(events: list[dict]) -> dict:
    """Single-pass computation of question answers and event resolutions.

    Resolution mechanism:
      - Questions: resolved by `answer` events that reference them
      - Goals, concerns, debt, decisions, assumptions: resolved via `metadata.resolves`
        array (any event with metadata.resolves: ["target-id"] resolves
        the target)

    Returns dict with:
      - question_answers: dict mapping question event ID → answer event
      - concern_resolutions: dict mapping concern event ID → resolving event
      - goal_resolutions: dict mapping goal event ID → resolving event
      - debt_resolutions: dict mapping debt event ID → resolving event
      - decision_resolutions: dict mapping decision event ID → resolving event
      - assumption_resolutions: dict mapping assumption event ID → resolving event
      - answered_question_ids: set of answered question IDs
      - resolved_concern_ids: set of resolved concern IDs
      - resolved_goal_ids: set of resolved goal IDs
      - resolved_debt_ids: set of resolved debt IDs
      - resolved_decision_ids: set of resolved decision IDs
      - resolved_assumption_ids: set of resolved assumption IDs
    """
    by_id: dict[str, dict] = {}
    question_answers: dict[str, dict] = {}
    concern_resolutions: dict[str, dict] = {}
    goal_resolutions: dict[str, dict] = {}
    debt_resolutions: dict[str, dict] = {}
    decision_resolutions: dict[str, dict] = {}
    assumption_resolutions: dict[str, dict] = {}

    for event in events:
        event_id = event.get("id", "")
        if event_id:
            by_id[event_id] = event

        # Question-answer linking: answer events reference questions
        if event.get("type") == "answer":
            for ref_id in event.get("references", []):
                ref_event = by_id.get(ref_id)
                if ref_event and ref_event.get("type") == "question":
                    question_answers[ref_id] = event

        # Explicit resolution via metadata.resolves
        for target_id in event.get("metadata", {}).get("resolves", []):
            resolved = resolve_prefix(target_id, by_id)
            if not resolved:
                continue
            full_id, target = resolved
            match target.get("type"):
                case "concern":
                    concern_resolutions[full_id] = event
                case "goal":
                    goal_resolutions[full_id] = event
                case "debt":
                    debt_resolutions[full_id] = event
                case "decision":
                    decision_resolutions[full_id] = event
                case "assumption":
                    assumption_resolutions[full_id] = event

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
    }


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
        if event.get("type") != "question":
            return
        if event.get("priority") != "\U0001f534":
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
