#!/usr/bin/env python3
"""Stop command hook: close-cycle gate.

Blocks Stop while a close skill is mid-cycle (CLOSE_CYCLE_ACTIVE marker
present), nudging the agent to invoke xp-close-reviewer next. The marker
is written by close skills before /security-review runs and consumed by
subagent_stop.py when xp-close-reviewer completes.

Defers on ASKING_USER so AskUserQuestion dialogues complete cleanly.
Review-cycle/teammates deferrals are intentionally NOT applied — the
close cycle wants to block mid-cycle by design.

stop_hook_active bypass: Claude Code latches `stop_hook_active=True`
session-wide once any Stop hook returns a `reason` (e.g.,
`session_end_warning`'s nudge) — it does NOT reset per-turn. Once the
flag is True, this gate's block message can no longer reach the agent
reliably, so the gate records a high-severity concern + emits stderr
(loud signal) AND consumes the CLOSE_CYCLE_ACTIVE marker
(abandoned-cycle signal). The concern + recovery prose tells the user
to manually finish the cycle next session; the marker clear prevents
the gate from re-firing every subsequent Stop in the session.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import event_schema
import identity
import markers

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
    """Record a concern, emit stderr, and consume the marker on bypass.

    `_common.append_safe` swallows LockTimeoutError internally and logs
    to hook_errors.jsonl, so the bypass record is best-effort by
    construction — no extra try/except needed. The stderr write is
    sequenced FIRST so the minimum signal lands even if append_safe is
    bypassed by a future regression.

    Marker consumption is sequenced LAST: by the time we get here, the
    cycle is empirically abandoned (stop_hook_active=True is latched
    session-wide). Leaving the marker would make every subsequent Stop
    in the session re-fire this gate and record duplicate concerns.
    `marker_consume` swallows OSError internally — best-effort.
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
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
