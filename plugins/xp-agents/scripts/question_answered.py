#!/usr/bin/env python3
"""PostToolUse/PostToolUseFailure:AskUserQuestion hook.

Handles both success and failure paths:
- Success with question gate: clears gate, records answer event
- Success without gate: logs customer_input with answer text
- Failure ("Chat about this..."): sets ASKING_USER marker so the stop
  gate defers, logs customer_input with partial answers
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import markers
import materialize
import resolution

_ANSWER_CONTENT_MAX = 500


def _open_blocking_question_ids(smm_dir: Path) -> list[str]:
    """Every 🔴 question id not yet resolved, in event-log order.

    Every currently-open 🔴 question blocks writes via QUESTION_GATE, so at
    answer-time each one is a question the user's answer just unblocked —
    even if a later 🔴 question clobbered the gate's single stored id first.
    Falls back to an empty list on any parse error so the caller degrades to
    today's single-question behavior instead of crashing the hook.
    """
    try:
        events, _ = materialize.parse_events(smm_dir)
        resolved = resolution.collect_all_resolved_ids(
            resolution.compute_resolutions(events)
        )
        return [
            e["id"]
            for e in events
            if e.get("type") == _common.QUESTION
            and e.get("priority") == resolution.event_schema.PRIORITY_BLOCKING
            and e.get("id") not in resolved
        ]
    except Exception:
        return []


def _extract_response_text(input_data: dict) -> str:
    """Extract displayable text from tool_response or error."""
    for field in ("error", "tool_response"):
        value = input_data.get(field)
        if not value:
            continue
        if isinstance(value, dict):
            return value.get("response", str(value))
        return str(value)
    return ""


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Handle AskUserQuestion success or failure."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)
    error = input_data.get("error")

    if error:
        markers.marker_write(smm_dir, markers.ASKING_USER, "1")
        if error.strip():
            event = _common.make_event(
                _common.CUSTOMER_INPUT,
                agent_id,
                _common.truncate(error, _ANSWER_CONTENT_MAX),
            )
            _common.append_safe(smm_dir, event)
        return None

    consumed = markers.marker_consume(smm_dir, markers.QUESTION_GATE)
    gate_id = consumed.strip() if isinstance(consumed, str) else ""

    response_text = _extract_response_text(input_data)

    refs = [gate_id] if gate_id else []
    for open_id in _open_blocking_question_ids(smm_dir):
        if open_id not in refs:
            refs.append(open_id)

    if refs:
        event = _common.make_event(
            _common.ANSWER,
            agent_id,
            f"Answer: {_common.truncate(response_text, _ANSWER_CONTENT_MAX)}",
            references=refs,
        )
        _common.append_safe(smm_dir, event)
    elif response_text:
        event = _common.make_event(
            _common.CUSTOMER_INPUT,
            agent_id,
            _common.truncate(response_text, _ANSWER_CONTENT_MAX),
        )
        _common.append_safe(smm_dir, event)

    return None


if __name__ == "__main__":
    run(_common.read_hook_input())
    sys.exit(0)
