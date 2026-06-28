#!/usr/bin/env python3
"""PreToolUse:Skill hook — inject guidance before skills run.

One injection:
- /code-review: courage nudge — review every change, act on every finding
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import target_routing

_CODE_REVIEW_COURAGE = (
    "Courage means doing the right thing even when it's uncomfortable. "
    "/code-review identifies correctness bugs but fixes nothing — every "
    "finding comes back unaddressed. Run it on every change, even ones that "
    "'look small'. The fix happens next in /xp-quality-review, where each "
    "valid finding must be addressed (or recorded as debt with a concrete "
    "reason) — never waved off as low-severity, pre-existing, or out of scope."
)


def run(input_data: dict, **_kwargs) -> str | None:
    """Inject guidance before skills run."""
    if _common.is_xp_agent(input_data):
        return None

    skill = input_data.get("tool_input", {}).get("skill", "")
    # Exact-match the built-in /code-review skill (bare or our-namespace-qualified).
    # Substring matching would catch xp-code-reviewer (our agent, not the skill)
    # and any third-party `otherplugin:code-review` skill.
    if target_routing.strip_our_namespace(skill) == "code-review":
        return _CODE_REVIEW_COURAGE

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PreToolUse", result)
    sys.exit(0)
