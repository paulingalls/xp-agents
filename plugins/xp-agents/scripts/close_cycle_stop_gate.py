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
yield and be re-woken by the workflow-completion notification. The
abandonment path (stop_hook_active bypass below) still fires in that
window. Teammates deferral is intentionally NOT applied — outside Step 4b
the close cycle wants to block mid-cycle by design.

stop_hook_active bypass: Claude Code latches `stop_hook_active=True`
session-wide once any Stop hook returns a `reason` (e.g.,
`session_end_warning`'s nudge) — it does NOT reset per-turn. Once the
flag is True, this gate's block message can no longer reach the agent
reliably, so the gate records a high-severity concern + emits stderr
(loud signal). The concern + recovery prose tells the user to manually
finish the cycle next session.

Marker consumption is age-gated: only markers older than
`_CLOSE_CYCLE_AGE_THRESHOLD_SEC` get consumed on bypass. A young marker
likely belongs to a genuine in-progress cycle that just coincided with
an unrelated earlier latch — keeping it lets xp-close-reviewer consume
it normally on the same close cycle. Marker mtime is set by
markers.marker_write at close-cycle start and is equivalent to the
preload's CLOSE_START_TS for this purpose.
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

# Close cycles typically complete in well under this window (~5 min
# happy path). Markers older than this are treated as truly-abandoned;
# younger markers stay so a genuine in-progress cycle survives an
# unrelated stop_hook_active latch. 10-min headroom absorbs slower
# concern-triage AskUserQuestion sessions inside the cycle.
_CLOSE_CYCLE_AGE_THRESHOLD_SEC = 600

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


def _record_bypass(smm_dir: Path, input_data: dict) -> None:
    """Record a concern, emit stderr, and conditionally consume the marker.

    Concern + stderr always emit (visibility into bypass events).
    Marker consumption is age-gated: old markers (abandoned cycle) get
    consumed so subsequent Stops don't re-fire; young markers (likely a
    genuine in-progress cycle latched by an unrelated hook) stay so
    xp-close-reviewer can consume them normally. A stat() OSError means
    the marker raced away between marker_exists() and here — skip
    cleanly.
    """
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

    marker_path = markers.marker_path(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    try:
        age = time.time() - marker_path.stat().st_mtime
    except OSError:
        return
    if age >= _CLOSE_CYCLE_AGE_THRESHOLD_SEC:
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
        agent_id = identity.resolve_agent_id(input_data)
        if markers.review_mid_cycle(smm_dir, agent_id):
            return None
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
