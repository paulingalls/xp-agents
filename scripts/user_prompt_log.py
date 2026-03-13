#!/usr/bin/env python3
"""UserPromptSubmit hook: log user prompts as customer_input events.

Records what the user said into the SMM so all agents can see it.
Truncates to 10,000 chars to prevent event bloat.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_MAX_PROMPT_LENGTH = 10_000


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core UserPromptSubmit logic."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    prompt = input_data.get("prompt", "")
    if isinstance(prompt, str) and len(prompt) > _MAX_PROMPT_LENGTH:
        prompt = prompt[:_MAX_PROMPT_LENGTH]

    event = _common.make_event(_common.CUSTOMER_INPUT, "customer", prompt)
    _common.append_safe(smm_dir, event)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
