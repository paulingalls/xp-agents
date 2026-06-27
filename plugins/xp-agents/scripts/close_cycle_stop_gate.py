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
marker is OLDER than `_CLOSE_CYCLE_AGE_THRESHOLD_SEC` is the cycle treated
as truly abandoned — then the gate records a high-severity concern + emits
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

# A close legitimately stays in-flight for the whole Step 4b window, whose
# threshold-gated `/code-review high` is an async multi-agent workflow that
# alone runs ~10-15 min (observed). The "still legitimately in-flight" window
# must therefore exceed that, plus headroom for /xp-quality-review consume,
# /security-review, and concern-triage AskUserQuestion sessions. Only markers
# OLDER than this are treated as truly-abandoned (block / record / consume);
# younger ones are a live cycle and are left alone. (Was 600s, which predated
# the workflow-backed /code-review and expired mid-Step-4b.)
_CLOSE_CYCLE_AGE_THRESHOLD_SEC = 1800

_BLOCK_MESSAGE = (
    "Close cycle mid-flight. Run /security-review then invoke "
    "xp-close-reviewer (Agent tool); then continue Steps 5-7."
)

_BYPASS_RECOVERY = (
    "Recovery: in next session, manually run /security-review then invoke "
    "xp-close-reviewer (Agent tool) to complete the close cycle, then "
    "re-attempt /xp-{sprint,plan,free}-close."
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


def _marker_young(smm_dir: Path) -> bool:
    """True if the CLOSE_CYCLE_ACTIVE marker is younger than the age threshold.

    A young marker means the close cycle plausibly just started (the async
    Step 4b /code-review workflow is still running, or stop_hook_active was
    latched by an unrelated hook). A stat() OSError means the marker raced
    away between marker_exists() and here — treat as NOT young so callers fall
    toward surfacing (block / consume) rather than a silent latch.
    """
    marker_path = markers.marker_path(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    try:
        age = time.time() - marker_path.stat().st_mtime
    except OSError:
        return False
    return age < _CLOSE_CYCLE_AGE_THRESHOLD_SEC


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
    if _marker_young(smm_dir):
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
        if markers.review_mid_cycle(smm_dir, agent_id) and _marker_young(smm_dir):
            return None
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
