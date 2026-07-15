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

_ANSWER_CONTENT_MAX = 500


def _gate_question_ids(consumed: object) -> list[str]:
    """Parse the consumed QUESTION_GATE into its accumulated 🔴 question ids.

    The gate accumulates one id per line (see _append_impl); consuming it
    yields the whole co-pending batch raised since the last answer. Resolution
    is bounded to THIS batch — never a log-wide sweep of every open 🔴, which
    would fabricate a resolution (and copy the wrong answer text) for an
    unrelated still-open question (a concurrent teammate's, or a stale one).
    Known narrow residual: a concurrent agent that arms the gate within the
    same answer window is still included — inherent to the single shared gate,
    but far tighter than the removed whole-log sweep.
    """
    if not isinstance(consumed, str):
        return []
    ids: list[str] = []
    for line in consumed.split("\n"):
        qid = line.strip()
        if qid and qid not in ids:
            ids.append(qid)
    return ids


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
    refs = _gate_question_ids(consumed)

    response_text = _extract_response_text(input_data)

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
