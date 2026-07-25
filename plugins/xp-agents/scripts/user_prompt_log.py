#!/usr/bin/env python3
"""UserPromptSubmit hook: log user prompts as customer_input events.

Truncates to 10,000 chars to prevent event bloat.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import hook_liveness
import markers

_MAX_PROMPT_LENGTH = 10_000


def _payload_session_id(input_data: dict) -> str | None:
    """The session id the runtime handed us, or None to use the env chain.

    `write_heartbeat` consults the candidate chain only for None. An empty
    string or a non-str would skip that fallback and key a marker on the hash
    of a value no reader ever addresses, so both normalise to None here.
    Twinned with the same helper in session_start — two short functions rather
    than a shared module, since the primitive they feed is owned elsewhere and
    neither hook imports the other.
    """
    raw = input_data.get("session_id")
    return (raw.strip() or None) if isinstance(raw, str) else None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core UserPromptSubmit logic. Returns additionalContext or None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # The PRIMARY hook-liveness write, and the only one a teammate gets: its
    # prompt is its entry point, so this lands before it can invoke anything
    # that would ask. Placed ahead of every early return below — those decide
    # whether this particular prompt is worth LOGGING, while the heartbeat
    # records that the hook RAN, which is true either way. A task notification
    # is not customer input; the runtime still fired. Never raises; a drop is
    # logged to hook_errors.jsonl.
    hook_liveness.write_heartbeat(smm_dir, session_id=_payload_session_id(input_data))

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
