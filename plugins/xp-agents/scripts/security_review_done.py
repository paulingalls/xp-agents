#!/usr/bin/env python3
"""PostToolUse:Skill hook: write security triage marker after /security-review.

When the built-in /security-review skill completes, write the
.security-triaged marker file so the commit gate clears.
(/xp-security-triage writes its own marker via mark_triaged.py.)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import security


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Write security triage marker if the Skill tool ran a security skill."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if "security-review" not in skill_name:
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    security.write_security_triaged(smm_dir)
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
