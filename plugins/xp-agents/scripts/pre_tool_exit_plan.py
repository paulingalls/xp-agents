#!/usr/bin/env python3
"""PreToolUse hook for ExitPlanMode: block until plan review runs.

If .plan-awaiting-review marker exists, the plan hasn't been reviewed.
Block ExitPlanMode so the agent runs /xp-plan-reviewer first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Block ExitPlanMode if plan review is pending."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    marker = smm_dir / ".plan-awaiting-review"
    if marker.exists() and not marker.is_symlink():
        raise _common.BlockedError(
            "Run the /xp-plan-reviewer skill before exiting plan mode.",
            "Plan review required before implementation.",
        )

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    try:
        run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    sys.exit(0)
