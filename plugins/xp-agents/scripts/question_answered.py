#!/usr/bin/env python3
"""PostToolUse:AskUserQuestion hook: clear question gate and record answer.

When a blocking question (🔴) was raised, the .question-gate file blocks
implementation until the user answers. This hook fires after AskUserQuestion
completes, clears the gate, and records an answer event resolving the
original question.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Clear question gate and record answer event."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Main agent just got a tool_result from AskUserQuestion — they're in
    # an interactive dialogue. Mark so sprint_stop_gate defers the next Stop.
    markers.marker_write(smm_dir, markers.ASKING_USER, "1")

    gate_file = smm_dir / ".question-gate"
    try:
        question_id = gate_file.read_text().strip()
        gate_file.unlink()
    except FileNotFoundError:
        return None

    if not question_id:
        return None

    # Extract answer text from tool response
    tool_response = input_data.get("tool_response", "")
    if isinstance(tool_response, dict):
        answer_text = tool_response.get("response", str(tool_response))
    else:
        answer_text = str(tool_response)

    # Truncate long answers
    if len(answer_text) > 500:
        answer_text = answer_text[:497] + "..."

    # Record answer event resolving the original question
    agent_id = input_data.get("agent_id", "main")
    event = _common.make_event(
        _common.ANSWER,
        agent_id,
        f"Answer: {answer_text}",
        references=[question_id],
    )
    _common.append_safe(smm_dir, event)

    return None


if __name__ == "__main__":
    run(_common.read_hook_input())
    sys.exit(0)
