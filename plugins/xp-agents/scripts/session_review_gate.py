#!/usr/bin/env python3
"""UserPromptSubmit hook: gate on .needs-session-review marker.

Blocks user prompts until /xp-session-review has been run. Allows
the session review command itself through. Respects enforcement mode.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common


def run(input_data: dict, smm_dir: Path | None = None) -> dict | None:
    """Check marker and block if session review needed.

    Returns a decision dict or None.
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
    if "/xp-session-review" in prompt:
        return None

    enforcement = _common.load_enforcement_mode()
    if enforcement == _common.ENFORCEMENT_ADVISORY:
        return None

    return {
        "decision": "block",
        "reason": (
            "Session review required. Run /xp-session-review to review "
            "open goals, concerns, decisions, and debt before proceeding."
        ),
    }


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result is not None:
        print(json.dumps(result))
    sys.exit(0)
