#!/usr/bin/env python3
"""SubagentStop command hook: deterministic plan analysis for plan_reviewer agent.

Fires when a Plan subagent completes. Counts steps, flags missing TDD strategy,
gathers all decisions/conventions from the SMM, and returns context for the
plan_reviewer agent hook via additionalContext.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_PLAN_CHARS = 5000
_MAX_DECISIONS = 20
_LARGE_PLAN_THRESHOLD = 10

_TEST_KEYWORDS = re.compile(
    r"\btests?\b|\btdd\b|\bspec\b|\bassert\b|\bverif",
    re.IGNORECASE,
)

_STEP_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_STEP_BULLET = re.compile(r"^\s*[-*]\s+", re.MULTILINE)


# ---------------------------------------------------------------------------
# Step counting
# ---------------------------------------------------------------------------


def count_steps(plan: str) -> int:
    """Count plan steps from numbered lists and bullet points."""
    numbered = len(_STEP_NUMBERED.findall(plan))
    bullets = len(_STEP_BULLET.findall(plan))
    return max(numbered, bullets)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core plan_review logic. Returns context string or None."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    plan_content = input_data.get("last_assistant_message", "")
    if not plan_content:
        return None

    agent_id = input_data.get("agent_id", "plan-subagent")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None

    # --- Analysis ---

    step_count = count_steps(plan_content)
    flags: list[str] = []

    # Size flag
    if step_count > _LARGE_PLAN_THRESHOLD:
        flags.append(
            f"Large plan: {step_count} steps (>{_LARGE_PLAN_THRESHOLD}). "
            "Consider splitting into smaller increments."
        )

    # TDD strategy check
    if not _TEST_KEYWORDS.search(plan_content):
        flags.append("No test/TDD strategy detected in the plan.")

    # Read events for decisions/conventions (capped to avoid context bloat)
    events = _common.read_events_raw(smm_dir)
    decisions: list[str] = []
    for e in events:
        if e.get("type") in (_common.DECISION, _common.CONVENTION):
            decisions.append(f"- [{e['type']}] {e['content']}")
            if len(decisions) >= _MAX_DECISIONS:
                break

    # Append status event recording the review
    status_event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"Plan review completed: {step_count} steps, {len(flags)} flags",
        working_on=[],
    )
    _common.append_safe(smm_dir, status_event)

    # --- Build context string ---

    parts: list[str] = []

    # Plan content (truncated)
    if len(plan_content) > _MAX_PLAN_CHARS:
        truncated_plan = plan_content[:_MAX_PLAN_CHARS]
        header = f"## Plan Content (truncated to {_MAX_PLAN_CHARS} chars)"
        parts.append(f"{header}\n\n{truncated_plan}\n\n[...truncated...]")
    else:
        parts.append(f"## Plan Content\n\n{plan_content}")

    parts.append(f"\n## Analysis\n\n- {step_count} steps detected")

    if flags:
        parts.append("\n## Flags\n")
        for flag in flags:
            parts.append(f"- {flag}")

    if decisions:
        parts.append("\n## Existing Decisions/Conventions\n")
        parts.extend(decisions)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    result = run(input_data)

    if result:
        _common.hook_output("SubagentStop", result)
    sys.exit(0)
