#!/usr/bin/env python3
"""PostToolUse:Skill hook: set review cycle flags after review skills complete.

Detects /simplify, /xp-quality-review, and /security-review skill completions.
Sets the corresponding flag in the review cycle marker so the commit gate
clears. For security, also writes the old .security-triaged marker for
backward compatibility with the below-threshold security-only path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers
import security


def _detect_review_flag(skill_name: str) -> str | None:
    """Map skill name to review cycle flag, or None if not a review skill."""
    if "simplify" in skill_name:
        return "simplify_done"
    if "quality-review" in skill_name:
        return "quality_review_done"
    if "security-review" in skill_name or "security-triage" in skill_name:
        return "security_review_done"
    return None


_NEXT_STEP: dict[str, str] = {
    "simplify_done": "Run /xp-quality-review next.",
    "quality_review_done": "Run /xp-security-triage next.",
    "security_review_done": "Review cycle complete — commit your changes now.",
}


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Set review cycle flags when review skills complete."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")
    agent_id = input_data.get("agent_id", "main")

    flag = _detect_review_flag(skill_name)
    if flag is None:
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    markers.set_review_flag(smm_dir, agent_id, flag)

    # Backward compat: security path also writes old-style marker
    if flag == "security_review_done":
        security.write_security_triaged(smm_dir)
        # Only record "review complete" when /security-review actually ran,
        # not when /xp-security-triage completed without running it.
        # mark_triaged.py already records the triage start event.
        if "security-review" in skill_name and "triage" not in skill_name:
            event = _common.make_event(
                _common.STATUS,
                "xp-security-review",
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
