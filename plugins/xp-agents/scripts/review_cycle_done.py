#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: set review cycle flags and inject post-
completion context after review skills or the xp-housekeeper agent run.

Detects /simplify, /xp-quality-review, and /security-review skill completions
via tool_input.skill, and the xp-housekeeper inline agent via
tool_input.subagent_type. Sets the corresponding flag in the review cycle
marker so the commit gate clears. For security, also writes the old
.security-triaged marker for backward compatibility with the below-threshold
security-only path. For housekeeping, injects PROCESS_GUIDE.md as context.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import markers
import security


def _detect_review_flag(target_name: str) -> str | None:
    """Map target name to review cycle flag, or None if not a review target."""
    if "simplify" in target_name:
        return "simplify_done"
    if "quality-review" in target_name:
        return "quality_review_done"
    if "security-review" in target_name or "security-triage" in target_name:
        return "security_review_done"
    return None


def _is_plan_review(target_name: str) -> bool:
    """Check if this is the plan review skill."""
    return "review-plan" in target_name


def _is_housekeeping(target_name: str) -> bool:
    """Match the forked housekeeping skill OR the housekeeper agent_type."""
    return "housekeeping" in target_name or "housekeeper" in target_name


_NEXT_STEP: dict[str, str] = {
    "simplify_done": "Run /xp-quality-review next.",
    "quality_review_done": "Run /security-review next.",
    "security_review_done": "Review cycle complete — commit your changes now.",
}

_TASK_CREATION_NUDGE = (
    "Use TaskCreate to break your plan into tasks before implementing. "
    "Each task should be one red-green-commit cycle. "
    "Mark tasks in_progress when you start them and completed when done."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Set review cycle flags when review skills complete."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    # Skill calls carry the target in tool_input.skill; Agent calls carry it
    # in tool_input.subagent_type. Both paths converge here so the housekeeper
    # can be invoked either way.
    target_name = tool_input.get("skill") or tool_input.get("subagent_type") or ""
    agent_id = identity.resolve_agent_id(input_data)

    # Housekeeping: inject process guide (not part of commit review cycle)
    if _is_housekeeping(target_name):
        return _common.load_process_guide() or None

    # Plan review: nudge task creation (not part of commit review cycle)
    if _is_plan_review(target_name):
        return _TASK_CREATION_NUDGE

    flag = _detect_review_flag(target_name)
    if flag is None:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    markers.set_review_flag(smm_dir, agent_id, flag)

    # Backward compat: security path also writes old-style marker
    if flag == "security_review_done":
        security.write_security_triaged(smm_dir, agent_id)
        # Only record "review complete" when /security-review actually ran,
        # not when /xp-security-triage completed without running it.
        # mark_triaged.py already records the triage start event.
        if "security-review" in target_name and "triage" not in target_name:
            event = _common.make_event(
                _common.STATUS,
                "security-review",
                "Security review complete — full review performed",
                working_on=[],
            )
            _common.append_safe(smm_dir, event)

    return _NEXT_STEP.get(flag)


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
