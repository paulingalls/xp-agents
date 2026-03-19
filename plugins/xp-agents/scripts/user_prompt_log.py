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
import security

_MAX_PROMPT_LENGTH = 10_000
_GOAL_NUDGE_TRACKER = ".goal-nudge-sent"
_BLOCK_GOALS = "block_goals"
_NUDGE_MESSAGE = "REMINDER: No project goals recorded yet. Run /xp-goal-collection."
_BLOCK_REASON = "No project goals recorded. Run /xp-goal-collection."

_SECURITY_REVIEW_PATTERN = re.compile(
    r"(?:/security-review\b|security\s+review|security\s+audit)", re.IGNORECASE
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core UserPromptSubmit logic. Returns additionalContext or None."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

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

    # Path 1: detect security review invocation in user prompt
    if isinstance(prompt, str) and _SECURITY_REVIEW_PATTERN.search(prompt):
        security.mark_security_reviewed(smm_dir, input_data.get("cwd", "."))

    # Goal collection — block first prompt of a goalless session.
    # Only block once (tracker file prevents infinite loop), then nudge.
    events = _common.read_events_raw(smm_dir)
    has_goals = any(e.get("type") == _common.GOAL for e in events)
    if not has_goals:
        tracker = smm_dir / _GOAL_NUDGE_TRACKER
        if not tracker.exists():
            tracker.write_text("")
            return _BLOCK_GOALS
        return _NUDGE_MESSAGE

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result == _BLOCK_GOALS:
        import json

        print(json.dumps({"decision": "block", "reason": _BLOCK_REASON}))
    elif result:
        _common.hook_output("UserPromptSubmit", result)
    sys.exit(0)
