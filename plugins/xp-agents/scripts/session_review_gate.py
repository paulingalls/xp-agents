#!/usr/bin/env python3
"""UserPromptSubmit hook: gate on .needs-session-review marker.

Blocks user prompts until /xp-session-review has been run. Allows
the session review command itself through. Respects enforcement mode.

Behavior depends on marker content:
- "startup" (new session): hard block
- "clear" (mid-session reset): nudge only (work may be in progress)

Task-notifications from background agents are always skipped.
"""

import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

_NUDGE = "nudge"

_REVIEW_MESSAGE = (
    "Session review required. Run /xp-session-review to review "
    "open goals, concerns, decisions, and debt before proceeding."
)


def run(input_data: dict, smm_dir: Path | None = None) -> dict | str | None:
    """Check marker and block/nudge if session review needed.

    Returns a decision dict, a nudge string, or None.
    """
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    marker = smm_dir / ".needs-session-review"
    if not marker.exists():
        return None

    prompt = input_data.get("prompt", "")

    # Skip task-notifications — background agent completions aren't user prompts
    if _common.is_task_notification(prompt):
        return None

    if "/xp-session-review" in prompt:
        return None

    enforcement = _common.load_enforcement_mode()
    if enforcement == _common.ENFORCEMENT_ADVISORY:
        return None

    # Read marker content to determine block vs nudge.
    # "clear" = mid-session reset, nudge only.
    # "startup" or empty = new session, hard block.
    source = ""
    with contextlib.suppress(OSError):
        source = marker.read_text().strip()

    if source == "clear":
        return _NUDGE

    return {
        "decision": "block",
        "reason": _REVIEW_MESSAGE,
    }


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result == _NUDGE:
        _common.hook_output("UserPromptSubmit", _REVIEW_MESSAGE)
    elif result is not None:
        result["systemMessage"] = "Session review required — run /xp-session-review."
        print(json.dumps(result))
    sys.exit(0)
