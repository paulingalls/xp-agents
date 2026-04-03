#!/usr/bin/env python3
"""PostToolUse:Skill hook: sprint review completion bookkeeping.

When /xp-sprint-review completes, recomputes velocity from sprint.md,
records the sprint end event, cleans up the review input file, and
nudges /xp-sprint-retro.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import sprint_parser
import sprint_state
from event_schema import EVENT_TYPE_SPRINT, SPRINT_ACTION_END

_REVIEW_NAMES = {"xp-sprint-review", "xp-agents:xp-sprint-review"}

_RETRO_NUDGE = (
    "\n\n---\n**Sprint review complete.** "
    "Run `/xp-sprint-retro` to reflect on the sprint."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Record sprint end event and nudge retro after sprint review."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")
    if skill_name not in _REVIEW_NAMES:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Recompute velocity from sprint.md (fresh, post-subagent)
    content = sprint_state.read_sprint_content(smm_dir)
    if content:
        sprint_data = sprint_parser.parse_sprint_data(content)
        velocity = sprint_parser.compute_velocity(sprint_data)
        sprint_id = sprint_data["sprint_id"] or "unknown"
        goal = sprint_data["goal"] or "Sprint review"

        event = _common.make_event(
            EVENT_TYPE_SPRINT,
            "sprint-review-done",
            f"Sprint end: {goal}. "
            f"{velocity['stories_delivered']}/{velocity['stories_planned']}"
            " stories delivered.",
            metadata={
                "sprint_id": sprint_id,
                "action": SPRINT_ACTION_END,
                **velocity,
            },
        )
        _common.append_safe(smm_dir, event)

    # Clean up review input file
    review_input = smm_dir / ".sprint-review-input.json"
    review_input.unlink(missing_ok=True)

    return _RETRO_NUDGE


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
