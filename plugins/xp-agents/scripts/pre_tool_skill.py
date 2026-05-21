#!/usr/bin/env python3
"""PreToolUse:Skill hook — inject guidance before skills run.

One injection:
- /code-review: courage nudge to run all 3 review subagents
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_SIMPLIFY_COURAGE = (
    "Courage means doing the right thing even when it's uncomfortable. "
    "/code-review requires launching 3 review subagents in parallel "
    "(code reuse, code quality, efficiency) — every time, on every change. "
    "Skipping subagents because the change 'looks small' is the easy path. "
    "Small changes hide duplication that only the code reuse agent catches "
    "by searching the broader codebase. Run all 3 agents."
)


def run(input_data: dict, **_kwargs) -> str | None:
    """Inject guidance before skills run."""
    if _common.is_xp_agent(input_data):
        return None

    skill = input_data.get("tool_input", {}).get("skill", "")

    if "code-review" in skill:
        return _SIMPLIFY_COURAGE

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PreToolUse", result)
    sys.exit(0)
