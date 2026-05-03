#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: set review cycle flags, emit canonical
lifecycle events, and inject post-completion context after review skills
or the xp-housekeeper agent run.

Detects /simplify, /xp-quality-review, /security-review, /xp-review-plan,
/xp-assign skill completions via tool_input.skill, and the xp-housekeeper
inline agent via tool_input.subagent_type. For each, appends a canonical
status event with metadata.action so consumers can detect skill completions
without regex-matching LLM-authored content. Per-commit review-cycle flags
are set only for /simplify and /xp-quality-review (M-4: security review
moved to Tier 2 at /xp-accept and Tier 3 at close).

The TaskCreate nudge fires after /xp-assign (not /xp-review-plan) because
execution mode (solo vs teammates) is decided by xp-assign — the nudge can
then describe mode-appropriate task shapes (per-step vs coordination).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import event_schema
import identity
import markers
import plugin_loader

# Canonical target names — derived from skill/agent names via _detect_target.
_TARGET_SIMPLIFY = "simplify"
_TARGET_QUALITY_REVIEW = "quality-review"
_TARGET_SECURITY_REVIEW = "security-review"
_TARGET_PLAN_REVIEW = "review-plan"
_TARGET_ASSIGN = "assign"
_TARGET_HOUSEKEEPING = "housekeeping"


def _detect_target(target_name: str) -> str | None:
    """Map a possibly-prefixed skill/agent name to its canonical target."""
    if "simplify" in target_name:
        return _TARGET_SIMPLIFY
    if "quality-review" in target_name:
        return _TARGET_QUALITY_REVIEW
    if "security-review" in target_name:
        return _TARGET_SECURITY_REVIEW
    if "review-plan" in target_name:
        return _TARGET_PLAN_REVIEW
    if "assign" in target_name:
        return _TARGET_ASSIGN
    if "housekeeping" in target_name or "housekeeper" in target_name:
        return _TARGET_HOUSEKEEPING
    return None


# Single dispatch table — target → (action, content) for the canonical
# lifecycle event. Hook is the single producer; consumers match
# metadata.action exactly so LLM-authored content drift cannot zero the
# counters. The event's agent_id is the teammate-resolved attribution
# (see agent-id-semantics ADR): skill identity lives in metadata.action.
# See docs/ideas/deterministic-event-emission.md.
_TARGET_LIFECYCLE: dict[str, tuple[str, str]] = {
    _TARGET_SIMPLIFY: (
        event_schema.STATUS_ACTION_SIMPLIFY_COMPLETE,
        "Simplify complete",
    ),
    _TARGET_QUALITY_REVIEW: (
        event_schema.STATUS_ACTION_QR_COMPLETE,
        "Quality review complete",
    ),
    _TARGET_SECURITY_REVIEW: (
        event_schema.STATUS_ACTION_SECURITY_COMPLETE,
        "Security review complete — full review performed",
    ),
    _TARGET_PLAN_REVIEW: (
        event_schema.STATUS_ACTION_PLAN_REVIEWED,
        "Plan reviewed",
    ),
    _TARGET_ASSIGN: (
        event_schema.STATUS_ACTION_ASSIGN_COMPLETE,
        "Assign complete",
    ),
    _TARGET_HOUSEKEEPING: (
        event_schema.STATUS_ACTION_HOUSEKEEPING_COMPLETE,
        "Housekeeping complete",
    ),
}


# Targets that participate in the per-commit review cycle (set the marker
# flag that clears the commit gate). plan-review and housekeeping are
# lifecycle-only — they don't gate commits.
_TARGET_FLAG: dict[str, str] = {
    _TARGET_SIMPLIFY: "simplify_done",
    _TARGET_QUALITY_REVIEW: "quality_review_done",
}


_NEXT_STEP: dict[str, str] = {
    "simplify_done": "Run /xp-quality-review next.",
    "quality_review_done": "Review cycle complete — commit your changes now.",
}


_TASK_CREATION_NUDGE = (
    "Use TaskCreate to track the upcoming work. Solo mode: one task per "
    "planned step (each = a red-green-commit cycle). Teammate mode: "
    "coordination tasks for waiting on each teammate, running /xp-accept "
    "per accepted story, and /xp-story-close per merged branch. Mark tasks "
    "in_progress when you start them and completed when done."
)


# /security-review's skill prompt ends with "reply must contain markdown
# report and nothing else" — correct for direct user invocations, but it
# stops orchestrated callers (xp-accept Tier 2, close-skill Tier 3) mid-
# flight. This nudge is delivered as PostToolUse:Skill additionalContext
# next to the tool result so the next model call sees both the skill's
# stop clause and this override; the calling agent has full context to
# decide whether to honor it (orchestrated → continue, direct user → stop).
_SECURITY_CONTINUATION_NUDGE = (
    "/security-review's 'reply with markdown report only' clause is intended "
    "for direct user invocations. If this call was part of an orchestrated "
    "flow (e.g. an xp-accept tier-2 gate or a close-skill tier-3 sweep), "
    "ignore that clause: record any findings as concerns at the appropriate "
    "severity, then proceed to the next step in the calling skill."
)


def _emit_action_event(smm_dir: Path, action: str, content: str, agent_id: str) -> None:
    """Append a canonical status event with metadata.action set."""
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        content,
        working_on=[],
        metadata={"action": action},
    )
    _common.append_safe(smm_dir, event)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Set review cycle flags and emit canonical lifecycle events."""
    tool_input = input_data.get("tool_input", {})
    # Skill calls carry the target in tool_input.skill; Agent calls carry it
    # in tool_input.subagent_type. Both paths converge here so the housekeeper
    # can be invoked either way. Target detection runs BEFORE the recursion-
    # prevention skip below so /security-review can be carved out as the one
    # exception — xp-close-reviewer (xp-*) is the primary intended caller of
    # the SECURITY_COMPLETE event (Tier 3) AND the continuation nudge.
    target_name = tool_input.get("skill") or tool_input.get("subagent_type") or ""
    target = _detect_target(target_name)
    if target is None:
        return None

    # Recursion-prevention: xp-* agents don't trigger our review-cycle flag
    # setting or simplify/QR/plan-review/housekeeping lifecycle events on
    # themselves. /security-review is excepted (see comment above).
    if _common.is_xp_agent(input_data) and target != _TARGET_SECURITY_REVIEW:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)

    # Per-commit review-cycle targets: set the marker flag that clears
    # the commit gate.
    flag = _TARGET_FLAG.get(target)
    if flag:
        markers.set_review_flag(smm_dir, agent_id, flag)

    # Emit canonical lifecycle event (single dispatch — producer determinism).
    # agent_id is the teammate-resolved attribution; skill identity lives
    # in metadata.action per the agent-id-semantics ADR.
    action, content = _TARGET_LIFECYCLE[target]
    _emit_action_event(smm_dir, action, content, agent_id)

    # Return appropriate context.
    if target == _TARGET_HOUSEKEEPING:
        return plugin_loader.load_process_guide() or None
    if target == _TARGET_ASSIGN:
        return _TASK_CREATION_NUDGE
    if target == _TARGET_SECURITY_REVIEW:
        return _SECURITY_CONTINUATION_NUDGE
    return _NEXT_STEP.get(flag) if flag else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
