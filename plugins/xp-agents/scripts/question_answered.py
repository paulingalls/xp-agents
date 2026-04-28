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

    gate_file = smm_dir / ".question-gate"
    try:
        question_id = gate_file.read_text().strip()
        gate_file.unlink()
    except FileNotFoundError:
        question_id = ""

    response_text = _extract_response_text(input_data)

    if question_id:
        event = _common.make_event(
            _common.ANSWER,
            agent_id,
            f"Answer: {_common.truncate(response_text, _ANSWER_CONTENT_MAX)}",
            references=[question_id],
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
