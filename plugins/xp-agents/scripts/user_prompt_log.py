#!/usr/bin/env python3
"""UserPromptSubmit hook: log user prompts as customer_input events.

Records what the user said into the SMM so all agents can see it.
Truncates to 10,000 chars to prevent event bloat.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import markers

_MAX_PROMPT_LENGTH = 10_000


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core UserPromptSubmit logic. Returns additionalContext or None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # User submitted a new prompt — any in-progress AskUserQuestion dialogue
    # is now resolved. Clear the marker so sprint_stop_gate resumes normal
    # blocking on the next Stop.
    markers.marker_consume(smm_dir, markers.ASKING_USER)

    prompt = input_data.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    # Skip task notifications — these are internal system messages,
    # not actual customer input. They create false loop boundaries.
    if _common.is_task_notification(prompt):
        return None

    if len(prompt) > _MAX_PROMPT_LENGTH:
        prompt = prompt[:_MAX_PROMPT_LENGTH]

    event = _common.make_event(_common.CUSTOMER_INPUT, "customer", prompt)
    _common.append_safe(smm_dir, event)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("UserPromptSubmit", result)
    sys.exit(0)
