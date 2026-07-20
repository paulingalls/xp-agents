#!/usr/bin/env python3
"""Stop command hook: close-cycle gate.

Blocks Stop while a close skill is mid-cycle (CLOSE_CYCLE_ACTIVE marker
present), nudging the agent to invoke xp-close-reviewer next. The marker
is written by close skills before /security-review runs and consumed by
subagent_stop.py when xp-close-reviewer completes.

Defers on ASKING_USER so AskUserQuestion dialogues complete cleanly.
Also defers during the close /code-review's async Step 4b window —
`markers.review_mid_cycle` (simplify_done set when the workflow launched,
quality_review_done not yet set when /xp-quality-review consumes its
findings). Pushing xp-close-reviewer there would run Step 4.5 BEFORE the
background /code-review returns; deferring (return None) lets the agent
yield and be re-woken by the workflow-completion notification. Teammates
deferral is intentionally NOT applied — outside Step 4b the close cycle
wants to block mid-cycle by design.

stop_hook_active bypass: Claude Code latches `stop_hook_active=True`
session-wide once any Stop hook returns a `reason` (e.g.,
`session_end_warning`'s nudge) — it does NOT reset per-turn. Once the
flag is True, this gate's block message can no longer reach the agent
reliably. The bypass is **age-gated**: only when the CLOSE_CYCLE_ACTIVE
marker is OLDER than `_CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC` is the cycle
treated as truly abandoned — then the gate records a high-severity concern + emits
stderr (loud signal) and consumes the marker. A YOUNG marker is a live
in-flight cycle (e.g. the agent yielding during the async Step 4b wait
with stop_hook_active already latched); recording an abandonment concern
there is a false positive, so the bypass leaves it alone (SessionStart
sweep is the backstop). Marker mtime is set by markers.marker_write at
close-cycle start and is equivalent to the preload's CLOSE_START_TS.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import event_schema
import identity
import markers
import target_routing

# Two distinct timescales, previously sharing one knob:
#
#   1. DEFER WINDOW — Step 4b is in flight, suppress the close-reviewer
#      nudge. Must EXCEED /code-review high's observed ~10-15 min runtime
#      plus headroom for /xp-quality-review consume + /security-review +
#      concern-triage AskUserQuestion. (Was 600s, which predated the
#      workflow-backed /code-review and expired mid-Step-4b; bumped to 1800s.)
#
#   2. ABANDONMENT TIMEOUT — the bypass-recorded "close abandoned" concern.
#      Must be SUBSTANTIALLY LONGER than the defer window so a slow but
#      legitimate close (security-review prompts, slow agent turns,
#      multi-round concern triage) doesn't trip a false-positive
#      abandonment.
#
# A single shared value forced a compromise that fails both: too long for
# defer (delays surfacing real abandonment) or too short for abandonment
# (false positives). The split keeps each knob honest to its purpose.
_CLOSE_CYCLE_DEFER_WINDOW_SEC = 1800
_CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC = 3600

_BLOCK_MESSAGE = (
    "Close cycle mid-flight. Run /security-review (Step 4) then "
    "/code-review high via the Workflow tool (Step 4b, if "
    "RUN_FULL_CODE_REVIEW=true) then invoke xp-close-reviewer (Agent tool, "
    "Step 4.5); then continue Steps 5-7."
)

_BYPASS_RECOVERY = (
    "Recovery: next session, run /security-review then /code-review high via "
    "the Workflow tool (if RUN_FULL_CODE_REVIEW=true) then invoke "
    "xp-close-reviewer (Agent tool); then re-attempt /xp-{sprint,plan,free}-close."
)
_BYPASS_CONCERN_CONTENT = (
    "Close-cycle gate bypassed: agent terminated via stop_hook_active "
    "while CLOSE_CYCLE_ACTIVE marker was set. xp-close-reviewer was "
    "expected to run but never did, leaving the close cycle mid-flight. "
    f"{_BYPASS_RECOVERY}"
)
_BYPASS_STDERR = (
    "close-cycle gate bypassed: stop_hook_active=True with "
    f"CLOSE_CYCLE_ACTIVE marker still set — high-severity concern recorded. "
    f"{_BYPASS_RECOVERY}\n"
)


def _marker_age(smm_dir: Path) -> float | None:
    """Marker age in seconds, or None if stat fails (marker raced away).

    Callers should treat None as 'cannot prove young' — fall toward
    surfacing (block / consume) rather than a silent latch.
    """
    marker_path = markers.marker_path(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    try:
        return time.time() - marker_path.stat().st_mtime
    except OSError:
        return None


def _marker_age_under(smm_dir: Path, threshold_sec: int) -> bool:
    """True if the CLOSE_CYCLE_ACTIVE marker is younger than ``threshold_sec``.

    Single helper for both the defer-window and abandonment-window checks —
    the two callers pass different constants but apply the identical
    None-handling semantics: a stat() OSError counts as NOT within the
    window so callers fall toward surfacing (block / consume / record)
    rather than silently latching.
    """
    age = _marker_age(smm_dir)
    if age is None:
        return False
    return age < threshold_sec


def reviewer_completed_this_cycle(
    smm_dir: Path, events: list[dict] | None = None
) -> bool:
    """True when xp-close-reviewer emitted a subagent_complete event AFTER the
    latest close_started in the log — evidence a reviewer RAN this cycle.

    The marker (CLOSE_CYCLE_ACTIVE) is written at close START, so its presence
    proves only that a close started, never that a reviewer ran. This reads the
    real lifecycle fact instead: subagent_stop._handle_close_reviewer_done emits
    the standard subagent_complete event when the close-reviewer stops. Ordering
    is by log/append position (mirroring retro_metrics' close-started scan) — no
    timestamp math; close_started is the current-cycle anchor.

    Fails CLOSED: a corrupt/failed event read (or any exception) is treated as
    'no evidence' → the caller keeps blocking. Never raises into the Stop hook.
    """
    event_action = event_schema.event_action
    close_started = event_schema.STATUS_ACTION_CLOSE_STARTED
    subagent_complete = event_schema.STATUS_ACTION_SUBAGENT_COMPLETE
    try:
        if events is None:
            events, _ = _common.load_events_with_resolutions(smm_dir)
        last_close_started = -1
        for i, event in enumerate(events):
            if event_action(event) == close_started:
                last_close_started = i
        if last_close_started < 0:
            return False
        for event in events[last_close_started + 1 :]:
            if event_action(event) != subagent_complete:
                continue
            agent_type = (event.get("metadata") or {}).get("agent_type", "")
            if (
                target_routing.strip_our_namespace(agent_type)
                == target_routing.CLOSE_REVIEWER_BARE
            ):
                return True
        return False
    except Exception:
        return False


def _record_bypass(smm_dir: Path, input_data: dict) -> None:
    """Record an abandonment concern and consume the marker — AGED markers only.

    A young marker is a legitimately in-flight close (e.g. the agent yielded
    during the async Step 4b `/code-review` wait, with `stop_hook_active`
    already latched session-wide by an unrelated earlier hook). That is NOT
    abandonment — the workflow-completion notification re-wakes the agent and
    the close finishes. Recording a high-severity "close abandoned" concern
    there is a false positive (the bug this guard fixes), so return early: no
    stderr, no concern, no consume; the SessionStart sweep is the backstop if a
    young cycle is genuinely abandoned.

    Once the marker ages past the threshold the cycle is truly stuck/abandoned:
    emit the loud signal (stderr + high-severity concern) and consume the marker
    so subsequent Stops don't re-fire. A stat() race (marker vanished) counts as
    not-young → falls through to consume (a harmless no-op).
    """
    if _marker_age_under(smm_dir, _CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC):
        return
    sys.stderr.write(_BYPASS_STDERR)
    agent_id = identity.resolve_agent_id(input_data)
    concern = _common.make_event(
        _common.CONCERN,
        agent_id,
        _BYPASS_CONCERN_CONTENT,
        severity="high",
        metadata={"kind": event_schema.CONCERN_KIND_CLOSE_CYCLE_BYPASS},
    )
    _common.append_safe(smm_dir, concern)
    markers.marker_consume(smm_dir, markers.CLOSE_CYCLE_ACTIVE)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message if close cycle is mid-flight, else None."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return None

    marker_active = markers.marker_exists(smm_dir, markers.CLOSE_CYCLE_ACTIVE)

    # Evidence releases a lingering marker. The block stays marker-triggered,
    # but a reviewer that already ran this cycle (subagent_complete emitted by
    # subagent_stop._handle_close_reviewer_done, after the latest close_started)
    # overrides it. Guard BEFORE the stop_hook_active bypass: Part 1 orders
    # emit-then-consume, so a crash between them can leave evidence + a lingering
    # marker; if that marker ages out and a stop_hook_active Stop fires,
    # _record_bypass would record a FALSE "reviewer never ran" concern despite
    # evidence it did. Releasing here closes that path. A genuine no-evidence
    # abandonment is untouched — no evidence → no early release → the aged
    # bypass still fires. Fails closed (bad read → no evidence → keep blocking).
    if marker_active and reviewer_completed_this_cycle(smm_dir):
        return None

    if input_data.get("stop_hook_active"):
        if marker_active:
            _record_bypass(smm_dir, input_data)
        return None

    if marker_active:
        # Step 4b window: the close /code-review workflow is in flight
        # (review mid-cycle). Defer the close-reviewer nudge until the
        # workflow returns and /xp-quality-review consumes its findings —
        # same predicate sprint_stop_gate uses, keyed to the gate's
        # resolved agent_id so the close /code-review's simplify_done
        # (written under that same key) is read here.
        #
        # Age-bound the defer (same threshold _record_bypass uses): defer
        # ONLY while the marker is young (workflow plausibly still running).
        # Once it ages past the threshold the mid-cycle flag is stuck — a
        # /xp-quality-review consume that never set quality_review_done — so
        # an unbounded defer would silently abandon the close forever. Fall
        # through to the block; the next stop_hook_active bypass then consumes
        # the aged marker and records the abandonment concern.
        agent_id = identity.resolve_agent_id(input_data)
        mid_cycle = markers.review_mid_cycle(smm_dir, agent_id)
        if mid_cycle and _marker_age_under(smm_dir, _CLOSE_CYCLE_DEFER_WINDOW_SEC):
            return None
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
