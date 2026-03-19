#!/usr/bin/env python3
"""PostToolUse:Skill hook: write security tracker after /security-review.

When the built-in /security-review skill completes, write the
.security-reviewed-{hash} tracker file so the push gate clears.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import security


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Write security tracker if the Skill tool ran security-review."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if skill_name != "security-review":
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    head_hash = security.get_head_hash()
    if head_hash is None:
        return None

    security.write_security_tracker(smm_dir, head_hash)
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
