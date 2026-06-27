#!/usr/bin/env python3
"""PostToolUse:Skill|Agent hook: set review-cycle flags, emit canonical
lifecycle events, inject post-completion context after review skills or
the xp-housekeeper agent.

Detects /code-review, /xp-quality-review, /security-review, /xp-review-plan,
/xp-assign via tool_input.skill, and xp-housekeeper via subagent_type.
Each appends a canonical status event with metadata.action so consumers
can detect completions without regex-matching LLM-authored content. The
per-commit review flag is set only for /code-review and /xp-quality-review.

Also detects /xp-schedule and /xp-sprint-review — accept's terminal dispatch —
and consumes ACCEPT_IN_FLIGHT there (the deterministic flip-to-in-progress
drain; no lifecycle event, no review flag). See _ACCEPT_TERMINAL_TARGETS.

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

# Canonical target names; mapped from skill/agent names by _detect_target.
_TARGET_SIMPLIFY = "simplify"
_TARGET_QUALITY_REVIEW = "quality-review"
_TARGET_SECURITY_REVIEW = "security-review"
_TARGET_PLAN_REVIEW = "review-plan"
_TARGET_ASSIGN = "assign"
_TARGET_HOUSEKEEPING = "housekeeping"
# Accept's terminal dispatch: /xp-accept always ends by invoking exactly one of
# these. Their handling drains ACCEPT_IN_FLIGHT but emits NO lifecycle event and
# sets NO review flag (see _ACCEPT_TERMINAL_TARGETS).
_TARGET_SCHEDULE = "schedule"
_TARGET_SPRINT_REVIEW = "sprint-review"


def _detect_target(target_name: str) -> str | None:
    """Map a possibly-prefixed skill/agent name to its canonical target."""
    # Built-in /code-review (formerly /simplify). Our own xp-code-reviewer agent
    # name also contains "code-review", and it arrives here via tool_input.
    # subagent_type when /xp-quality-review spawns it — but in the MAIN agent's
    # PostToolUse context, so the is_xp_agent skip in run() (which checks the
    # invoking agent_type, not subagent_type) does NOT fire. Guard explicitly.
    if "code-review" in target_name and "code-reviewer" not in target_name:
        return _TARGET_SIMPLIFY
    if "quality-review" in target_name:
        return _TARGET_QUALITY_REVIEW
    if "security-review" in target_name:
        return _TARGET_SECURITY_REVIEW
    if "review-plan" in target_name:
        return _TARGET_PLAN_REVIEW
    # /xp-sprint-review — accept's all-done terminal dispatch. "sprint-review" is
    # not a substring of any review skill matched above (quality-review /
    # security-review / review-plan / code-review), so the ordering here is safe.
    # The xp-sprint-reviewer AGENT name also contains "sprint-review" and maps
    # here — harmless: it fires within accept's terminal window and only drains
    # ACCEPT_IN_FLIGHT (no flag, no lifecycle event).
    if "sprint-review" in target_name:
        return _TARGET_SPRINT_REVIEW
    if "schedule" in target_name:
        return _TARGET_SCHEDULE
    if "assign" in target_name:
        return _TARGET_ASSIGN
    if "housekeeping" in target_name or "housekeeper" in target_name:
        return _TARGET_HOUSEKEEPING
    return None


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


# Accept's terminal dispatch consumes ACCEPT_IN_FLIGHT (Fix 2). These targets
# deliberately have NO _TARGET_LIFECYCLE entry — the lookup in run() is guarded
# with .get() so they emit no spurious review-lifecycle event (consumers count
# those) and raise no KeyError.
_ACCEPT_TERMINAL_TARGETS: frozenset[str] = frozenset(
    {_TARGET_SCHEDULE, _TARGET_SPRINT_REVIEW}
)


_NEXT_STEP: dict[str, str] = {
    "simplify_done": "Run /xp-quality-review next.",
    "quality_review_done": "Review cycle complete — commit your changes now.",
}


_TASK_CREATION_NUDGE = (
    "Use TaskCreate to track the upcoming work. Solo mode: one task per "
    "planned step (each = a red-green-commit cycle). Teammate mode: "
    "coordination tasks for waiting for each teammate to self-promote a "
    "story to `reviewing`, then running /xp-accept incrementally (it "
    "dispatches /xp-story-close per accepted story). Loop until all "
    "teammates finish; do not wait for the slowest. Mark tasks "
    "in_progress when you start them and completed when done."
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

    # /xp-accept's terminal dispatch (exactly one of /xp-schedule or
    # /xp-sprint-review) is accept's deterministic terminal signal. Drain
    # ACCEPT_IN_FLIGHT here — at the real flip-to-in-progress
    # event (/xp-schedule promotes the next frontier story) — rather than via a
    # state-derived check that can never observe a drained loop once the next
    # story is promoted. Idempotent: marker_consume is a no-op when unarmed
    # (e.g. the kickoff-tail /xp-schedule). This is a pre-emit side-effect; the
    # guarded lifecycle lookup below skips emit for these no-entry targets.
    if target in _ACCEPT_TERMINAL_TARGETS:
        markers.marker_consume(smm_dir, markers.ACCEPT_IN_FLIGHT)

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
