#!/usr/bin/env python3
"""One owner of the "a close cycle died mid-flight" record.

The close-cycle marker is armed at close START and released only when
xp-close-reviewer completes, so EVERY exit before that reviewer leaves it
behind — a Step 0 gate refusal, a pre-flight/push/PR failure, an interrupt
anywhere in the middle. Three separate components can be the first to find the
survivor, and each of them used to have the option of just deleting it:

  - `close_cycle_stop_gate` — an aged marker on a Stop the platform's
    re-entry flag has already latched (the gate ALLOWS that stop, deliberately;
    recording is what makes the allow honest).
  - `session_markers.sweep_stale_session_markers` — the marker survived to the
    next fresh session start.
  - the close preloads — a new close is arming over a survivor, and the arm
    overwrites it, so it has to be read out first (which is NOT the same as
    the previous cycle being dead: see the age rule below).

They share one content and one budget owner here because two hand-rolled
constructions would drift, and only one of them would be budget-pinned: an
over-budget concern fails schema validation and never lands, which is a real
prior outage on this exact record. `metadata.detector` is what tells the three
apart in the log.

They also share the AGE rule (`ABANDONMENT_MIN_AGE_SEC`), which is what makes
the record mean anything: bare marker existence cannot tell an abandoned cycle
from one that is still running, and two of the three detectors routinely see
the latter.

Recording CONSUMES the marker, so a cycle recorded by one detector is normally
invisible to the next. That is a narrow window, not an interlock — the three
run in separate processes with no lock, so two that observe the same aged
survivor within the same instant can both record. The age rule is what keeps
that instant rare; a duplicate costs an operator one extra resolve, where a
missed record costs the whole signal.

Degrades quiet. Every caller is a cleanup path — a hook, a sweep, a preload —
and none of them may fail a session because an append failed. But a DROPPED
append keeps the marker: consuming it would destroy the only evidence the
cycle died, and no later detector could re-find it. So the consume is
conditional on the append landing, and the return value says which happened.
"""

import contextlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import event_schema
import identity
import markers

# Which component found the survivor. Carried in metadata, never in the
# content — one content is the point of this module.
DETECTOR_AGED_STOP = "aged_stop"
DETECTOR_SESSION_SWEEP = "session_sweep"
DETECTOR_CLOSE_RESTART = "close_restart"

DETECTORS = (DETECTOR_AGED_STOP, DETECTOR_SESSION_SWEEP, DETECTOR_CLOSE_RESTART)

# Names the three closes that ARM the gate, and deliberately not story-close:
# that mode's review path never forks the close reviewer, so sending an
# operator to re-run it would be sending them to the wrong close.
RECOVERY = (
    "Recovery: next session, run /security-review then /code-review high via "
    "the Workflow tool (if RUN_FULL_CODE_REVIEW=true) then invoke "
    "xp-close-reviewer (Agent tool); then re-attempt /xp-{sprint,plan,free}-close."
)
CONCERN_CONTENT = (
    "Close cycle abandoned: the close-cycle marker was still set when the "
    "cycle ended, so xp-close-reviewer was expected to run but never did — "
    f"the branch was left mid-close. {RECOVERY}"
)

# How old the marker must be before its survival counts as abandonment.
#
# Bare existence cannot decide it. The marker is not session-scoped and the SMM
# is shared across windows and worktrees, so a detector routinely sees a cycle
# that is LIVE somewhere else; and the preloads arm it at skill load, BEFORE
# the close's own first gate can refuse — so a red-gate retry finds a survivor
# it created seconds ago. Recording either files a high-severity concern that
# the close's own count reads as a reason to abort a close that never failed.
#
# Longer than `close_cycle_stop_gate`'s defer window by design: a slow but
# legitimate close must age out of the defer before it can age into this.
ABANDONMENT_MIN_AGE_SEC = 3600


def marker_age_seconds(smm_dir: Path) -> float | None:
    """Seconds since the close-cycle marker was armed, or None when unusable.

    None means "no marker to age" — absent (the normal case on every path that
    asks), a symlink, or raced away between the two syscalls. Callers treat it
    as nothing-to-record, never as old.
    """
    if not markers.marker_exists(smm_dir, markers.CLOSE_CYCLE_ACTIVE):
        return None
    try:
        mtime = markers.marker_path(smm_dir, markers.CLOSE_CYCLE_ACTIVE).stat().st_mtime
    except OSError:
        return None
    return time.time() - mtime


def record_abandonment(smm_dir: Path, detector: str, agent_id: str = "") -> bool:
    """Record the abandonment concern, then consume the marker.

    Returns True only when a concern actually LANDED in the log. Three ways it
    returns False, and none of them consumes the marker:

    - no marker (the normal case on every path that calls this — recording
      there would turn a real signal into a per-session tax nobody reads);
    - a marker younger than `ABANDONMENT_MIN_AGE_SEC`, which is a live cycle in
      this window or another, not an abandoned one;
    - a dropped append, which leaves the marker for the next detector rather
      than destroying the evidence along with the record of it.

    `agent_id` defaults to the cwd-derived id, the same resolution every
    skill-invoked script without hook input uses.
    """
    if detector not in DETECTORS:
        raise ValueError(f"unknown detector {detector!r}; expected one of {DETECTORS}")
    age = marker_age_seconds(smm_dir)
    if age is None or age < ABANDONMENT_MIN_AGE_SEC:
        return False
    if not _append_record(smm_dir, detector, agent_id):
        return False
    markers.marker_consume(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    return True


def _append_record(smm_dir: Path, detector: str, agent_id: str) -> bool:
    """Append the concern and report whether it landed. Never raises.

    `_common.append_safe` is the house wrapper, and it is the wrong one HERE
    for one reason: it returns None. It logs a drop to hook_errors.jsonl and
    carries on, which is right for a caller whose next step does not depend on
    the append — but this one's does. So the append is made directly and its
    failure is logged through the same channel, with the drop reported back
    instead of swallowed.
    """
    import _append_impl

    try:
        event = _common.make_event(
            _common.CONCERN,
            agent_id or identity.resolve_agent_id_from_cwd(os.getcwd()),
            CONCERN_CONTENT,
            severity="high",
            metadata={
                "kind": event_schema.CONCERN_KIND_CLOSE_CYCLE_BYPASS,
                "detector": detector,
            },
        )
        errors = _append_impl.validate_event(event)
        if errors:
            raise ValueError("; ".join(errors))
        _append_impl.append_event(smm_dir, event)
        return True
    except Exception as exc:
        with contextlib.suppress(Exception):
            _common.log_hook_error(
                f"abandonment record dropped ({detector}): {exc}",
                error_class=type(exc).__name__,
            )
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI for the shell callers (the close preloads' record-before-arm)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Record an abandoned close cycle and clear its marker"
    )
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--detector", required=True, choices=DETECTORS)
    parser.add_argument("--agent-id", default="")
    args = parser.parse_args(argv)
    record_abandonment(Path(args.smm_dir), args.detector, args.agent_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
