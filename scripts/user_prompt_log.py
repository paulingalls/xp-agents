#!/usr/bin/env python3
"""UserPromptSubmit hook: log user prompts as customer_input events.

Records what the user said into the SMM so all agents can see it.
Truncates to 10,000 chars to prevent event bloat.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_MAX_PROMPT_LENGTH = 10_000

_SECURITY_REVIEW_PATTERN = re.compile(
    r"(?:/security-review\b|security\s+review|security\s+audit)", re.IGNORECASE
)


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

    # Path 1: detect security review invocation in user prompt
    if isinstance(prompt, str) and _SECURITY_REVIEW_PATTERN.search(prompt):
        head_hash = _common.get_head_hash()
        if head_hash is not None:
            _common.write_security_tracker(smm_dir, head_hash)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
