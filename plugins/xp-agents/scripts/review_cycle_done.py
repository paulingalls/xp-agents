#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: set review-cycle flags, emit canonical
lifecycle events, inject post-completion context after review skills or
the xp-housekeeper agent.

Detects /code-review, /xp-quality-review, /security-review, /xp-review-plan,
/xp-assign via tool_input.skill, and xp-housekeeper via subagent_type.
Each appends a canonical status event with metadata.action so consumers
can detect completions without regex-matching LLM-authored content. The
per-commit review flag is set only for /code-review and /xp-quality-review.

ACCEPT_IN_FLIGHT drain lives in a sibling hook (accept_terminal.py) — this
hook owns review-cycle lifecycle, that one owns accept-marker lifecycle.

TaskCreate nudge fires after /xp-assign (not /xp-review-plan) because
/xp-assign runs only for the teammate batch /xp-schedule already promoted —
by then the execution mode is settled, so the nudge can describe
teammate-appropriate task shapes.
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
import target_routing

# Canonical target names; mapped from skill/agent names by _detect_target.
_TARGET_SIMPLIFY = "simplify"
_TARGET_QUALITY_REVIEW = "quality-review"
_TARGET_SECURITY_REVIEW = "security-review"
_TARGET_PLAN_REVIEW = "review-plan"
_TARGET_ASSIGN = "assign"
_TARGET_HOUSEKEEPING = "housekeeping"


# Explicit allowlist: incoming skill/agent name -> canonical target. Closed set
# (built-in skills + plugin-internal xp-* names). The xp-code-reviewer agent's
# bare and qualified forms are absent by construction, so no substring guard
# is needed; future names like xp-quality-reviewer-helper are also safe.
_TARGET_BY_NAME: dict[str, str] = {
    "code-review": _TARGET_SIMPLIFY,
    "xp-quality-review": _TARGET_QUALITY_REVIEW,
    "security-review": _TARGET_SECURITY_REVIEW,
    "xp-review-plan": _TARGET_PLAN_REVIEW,
    "xp-assign": _TARGET_ASSIGN,
    "xp-housekeeper": _TARGET_HOUSEKEEPING,
}


def _detect_target(target_name: str) -> str | None:
    """Map a skill/agent name to its canonical target via explicit allowlist.

    Accepts bare (`xp-assign`) and OUR-plugin-qualified
    (`xp-agents:xp-assign`) forms via `target_routing.strip_our_namespace`.
    Third-party plugins (`otherplugin:<name>`) return None.
    """
    bare = target_routing.strip_our_namespace(target_name)
    if bare is None:
        return None
    return _TARGET_BY_NAME.get(bare)


# Single dispatch table — target → (action, content). Hook is the sole
# producer; consumers match metadata.action exactly so LLM-authored content
# drift can't zero the counters. agent_id is teammate-resolved attribution
# (skill identity lives in metadata.action per agent-id-semantics ADR).
_TARGET_LIFECYCLE: dict[str, tuple[str, str]] = {
    _TARGET_SIMPLIFY: (
        event_schema.STATUS_ACTION_SIMPLIFY_COMPLETE,
        "Code review complete",
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


# Per-commit review-cycle targets — set the marker flag that clears the
# commit gate. plan-review/housekeeping are lifecycle-only, don't gate commits.
_TARGET_FLAG: dict[str, str] = {
    _TARGET_SIMPLIFY: "simplify_done",
    _TARGET_QUALITY_REVIEW: "quality_review_done",
}


_NEXT_STEP: dict[str, str] = {
    "simplify_done": "Run /xp-quality-review next.",
    "quality_review_done": "Review cycle complete — commit your changes now.",
}


_TASK_CREATION_NUDGE = (
    "Use TaskCreate to track the upcoming work. This /xp-assign just spawned "
    "ONE teammate (per-story pipeline — not a batch); add a task to plan the "
    "NEXT teammate-mode story (EnterPlanMode -> /xp-review-plan -> /xp-assign), "
    "plus a coordination task to read this teammate's task-notification when it "
    "lands and run /xp-accept on it. Mark tasks in_progress when you start "
    "them and completed when done."
)


# /security-review's prompt ends with a stop clause ("reply must contain
# markdown report and nothing else") — fine for direct user invocations,
# but it halts orchestrated callers (close-skill Step 4.5) mid-flight.
# This nudge ships next to the tool result so the calling agent sees both
# the stop clause and the override and decides which applies in context.
_SECURITY_CONTINUATION_NUDGE = (
    "/security-review's 'reply with markdown report only' clause is intended "
    "for direct user invocations. If this call was part of an orchestrated "
    "flow (e.g. a /xp-{free,sprint,plan}-close Step 4.5 gate), ignore that "
    "clause: record any findings as concerns at the appropriate severity, "
    "then proceed to the next step in the calling skill."
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
    # Skill carries target in tool_input.skill; Agent in tool_input.subagent_type.
    # Detection runs BEFORE recursion-prevention so /security-review can be
    # carved out — orchestrated callers (close-skill Step 4.5) need both the
    # SECURITY_COMPLETE event and the continuation nudge to proceed.
    target_name = tool_input.get("skill") or tool_input.get("subagent_type") or ""
    target = _detect_target(target_name)
    if target is None:
        return None

    # Recursion-prevention: xp-* agents don't trigger flag-setting or lifecycle
    # events on themselves. /security-review is excepted (see comment above).
    if _common.is_xp_agent(input_data) and target != _TARGET_SECURITY_REVIEW:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)

    flag = _TARGET_FLAG.get(target)
    if flag:
        markers.set_review_flag(smm_dir, agent_id, flag)

    lifecycle = _TARGET_LIFECYCLE.get(target)
    if lifecycle is not None:
        action, content = lifecycle
        _emit_action_event(smm_dir, action, content, agent_id)

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
