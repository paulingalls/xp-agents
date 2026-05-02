#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: set review cycle flags, emit canonical
lifecycle events, and inject post-completion context after review skills
or the xp-housekeeper agent run.

Detects /simplify, /xp-quality-review, /security-review, /xp-security-triage,
/xp-review-plan skill completions via tool_input.skill, and the xp-housekeeper
inline agent via tool_input.subagent_type. For each, appends a canonical
status event with metadata.action so consumers can detect skill completions
without regex-matching LLM-authored content. Per-commit review-cycle flags
are set only for /simplify and /xp-quality-review (M-4: security review moved
to Tier 2 at /xp-accept and Tier 3 at close). Security skills still write the
.security-triaged marker so Tier 2/3 paths can observe triage history; the
marker helpers are slated for removal in M-5.
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
import security

# Canonical target names — derived from skill/agent names via _detect_target.
_TARGET_SIMPLIFY = "simplify"
_TARGET_QUALITY_REVIEW = "quality-review"
_TARGET_SECURITY_REVIEW = "security-review"
_TARGET_SECURITY_TRIAGE = "security-triage"
_TARGET_PLAN_REVIEW = "review-plan"
_TARGET_HOUSEKEEPING = "housekeeping"


def _detect_target(target_name: str) -> str | None:
    """Map a possibly-prefixed skill/agent name to its canonical target.

    Order matters: security-triage must check before security-review (the
    triage name contains 'security-' but means a different lifecycle moment).
    """
    if "simplify" in target_name:
        return _TARGET_SIMPLIFY
    if "quality-review" in target_name:
        return _TARGET_QUALITY_REVIEW
    if "security-triage" in target_name:
        return _TARGET_SECURITY_TRIAGE
    if "security-review" in target_name:
        return _TARGET_SECURITY_REVIEW
    if "review-plan" in target_name:
        return _TARGET_PLAN_REVIEW
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
    _TARGET_SECURITY_TRIAGE: (
        event_schema.STATUS_ACTION_SECURITY_TRIAGE_COMPLETE,
        "Security triage complete",
    ),
    _TARGET_PLAN_REVIEW: (
        event_schema.STATUS_ACTION_PLAN_REVIEWED,
        "Plan reviewed",
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
    "Use TaskCreate to break your plan into tasks before implementing. "
    "Each task should be one red-green-commit cycle. "
    "Mark tasks in_progress when you start them and completed when done."
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
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    # Skill calls carry the target in tool_input.skill; Agent calls carry it
    # in tool_input.subagent_type. Both paths converge here so the housekeeper
    # can be invoked either way.
    target_name = tool_input.get("skill") or tool_input.get("subagent_type") or ""
    target = _detect_target(target_name)
    if target is None:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)

    # Per-commit review-cycle targets: set marker (commit gate),
    # write security-triaged for the security paths.
    flag = _TARGET_FLAG.get(target)
    if flag:
        markers.set_review_flag(smm_dir, agent_id, flag)
    if target in (_TARGET_SECURITY_REVIEW, _TARGET_SECURITY_TRIAGE):
        security.write_security_triaged(smm_dir, agent_id)

    # Emit canonical lifecycle event (single dispatch — producer determinism).
    # agent_id is the teammate-resolved attribution; skill identity lives
    # in metadata.action per the agent-id-semantics ADR.
    action, content = _TARGET_LIFECYCLE[target]
    _emit_action_event(smm_dir, action, content, agent_id)

    # Return appropriate context.
    if target == _TARGET_HOUSEKEEPING:
        return plugin_loader.load_process_guide() or None
    if target == _TARGET_PLAN_REVIEW:
        return _TASK_CREATION_NUDGE
    return _NEXT_STEP.get(flag) if flag else None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
