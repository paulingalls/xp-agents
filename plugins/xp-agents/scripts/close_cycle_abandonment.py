#!/usr/bin/env python3
"""One owner of the "a close cycle died mid-flight" record.

The close-cycle marker is armed at close START, and the happy path releases it
when xp-close-reviewer completes — so EVERY exit before that reviewer leaves it
behind: a Step 0 gate refusal, a pre-flight/push/PR failure, an interrupt
anywhere in the middle. (Recording below releases it too; that is this module's
whole job.) Three separate components can be the first to find the survivor,
and each of them used to have the option of just deleting it:

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

They also share the decision itself, because bare marker existence cannot tell
an abandoned cycle from a running one and two of the three routinely see the
latter. The OWNING SESSION decides it; `ABANDONMENT_MIN_AGE_SEC` is the shared
fallback for an owner that cannot be named or read, not the primary rule.

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
import hook_liveness
import identity
import markers
import session_markers

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
    "the Skill tool (if RUN_FULL_CODE_REVIEW=true) then invoke "
    "xp-close-reviewer (Agent tool); then re-attempt /xp-{sprint,plan,free}-close."
)
CONCERN_CONTENT = (
    "Close cycle abandoned: the close-cycle marker was still set when the "
    "cycle ended, so xp-close-reviewer was expected to run but never did — "
    f"the branch was left mid-close. {RECOVERY}"
)

# Fallback only. The marker's OWNING SESSION decides abandonment; age decides
# only when that session cannot be named or its heartbeat cannot be read.
#
# Bare existence cannot decide it. The marker is not session-scoped and the SMM
# is shared across windows and worktrees, so a detector routinely sees a cycle
# that is LIVE somewhere else; and the preloads arm it at skill load, BEFORE
# the close's own first gate can refuse — so a red-gate retry finds a survivor
# it created seconds ago. Recording either files a high-severity concern that
# the close's own count reads as a reason to abort a close that never failed.
#
# A DURATION cannot decide it either, which is why this is no longer the
# primary rule. The marker carries only an mtime, and a close's runtime is
# unbounded: the close that shipped this very change ran 4429s while perfectly
# healthy, past the hour this constant allows. No fixed threshold is
# simultaneously long enough for a slow live close and short enough for a dead
# one — it only moves the false record later.
#
# Longer than `close_cycle_stop_gate`'s defer window by design: a slow but
# legitimate close must age out of the defer before it can age into this.
ABANDONMENT_MIN_AGE_SEC = 3600


def owner_session_is_live(smm_dir: Path, session_id: str) -> bool | None:
    """Is the session that armed the marker still running?

    The discriminator a duration was standing in for. Every session writes a
    per-session heartbeat into this same shared SMM, so a detector in ANOTHER
    window can address the arming session's heartbeat by id and ask directly
    whether that close is still alive.

    Returns None for "cannot tell" — no id recorded (a marker armed by an
    older version), or a heartbeat that is absent, symlinked or unageable.
    Callers fall back to age there: for an owner nobody can name, a false
    record breaks a healthy close while a missed one only loses a signal.

    A heartbeat FURTHER AHEAD than the skew grace is unageable in that same
    sense, not fresh — `session_markers.marker_age_seconds` hands a future
    timestamp back as a negative number and leaves the bound to its callers.
    That leg does NOT inherit the asymmetry: "live" there is PERMANENT (every
    negative age is under the stale threshold), so nothing ever consumes the
    marker and the gate blocks every Stop for good — worse than one concern an
    operator resolves. Pinned in test_close_cycle_owner_liveness.py.
    """
    if not session_id:
        return None
    data = markers.marker_read(smm_dir, hook_liveness.heartbeat_marker(session_id))
    if not isinstance(data, dict):
        return None
    age = session_markers.marker_age_seconds(time.time(), data.get("written_at"))
    if age is None or age < -hook_liveness.FUTURE_SKEW_GRACE_SECONDS:
        return None
    return age < hook_liveness.STALE_AFTER_SECONDS


def arm_close_cycle(smm_dir: Path) -> None:
    """Arm the marker, stamping the session that owns this close.

    The payload is what makes `owner_session_is_live` answerable at all: a
    detector in another window has no other way to tell whose close it found.
    An unresolvable session id writes empty, which is the same state every
    marker armed by an older version is in — decidable by age alone, and
    exactly what the fallback exists for.
    """
    markers.marker_write(
        smm_dir, markers.CLOSE_CYCLE_ACTIVE, hook_liveness.resolve_session_id() or ""
    )


def _is_abandoned(smm_dir: Path) -> bool:
    """Decide abandonment: owning session first, age only as a fallback."""
    age = marker_age_seconds(smm_dir)
    if age is None:
        return False
    owner = markers.marker_read(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    owner_id = owner.strip() if isinstance(owner, str) else ""
    live = owner_session_is_live(smm_dir, owner_id)
    if live is not None:
        # The owner answered. A live owner is a running close no matter how
        # long it has run; a dead one is abandoned no matter how recently it
        # died — neither reading depends on the clock.
        return not live
    return age >= ABANDONMENT_MIN_AGE_SEC


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
    - a marker whose owning session is still LIVE, which is a running close in
      this window or another, not an abandoned one (see `_is_abandoned`);
    - a dropped append, which leaves the marker for the next detector rather
      than destroying the evidence along with the record of it.

    `agent_id` defaults to the cwd-derived id, the same resolution every
    skill-invoked script without hook input uses.
    """
    if detector not in DETECTORS:
        raise ValueError(f"unknown detector {detector!r}; expected one of {DETECTORS}")
    if not _is_abandoned(smm_dir):
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
    parser.add_argument("--agent-id", default="")
    # Mutually exclusive and required so argparse writes the "one of these is
    # required" message itself. A hand-rolled equivalent would be prose this
    # module ships, and its reason budget is spent on the two strings that
    # reach a user's context window, not on CLI plumbing.
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--detector", choices=DETECTORS)
    # Arming is a SEPARATE invocation from recording, not a tail of it, because
    # the two must straddle the close's CLOSE_START_TS stamp: the record is
    # about the PREVIOUS cycle and has to land before the window this close
    # counts high concerns in, while the marker being armed belongs to this
    # one. Folding them into one call moved the record after the stamp and
    # reintroduced the false abort-default a prior commit had just closed.
    mode.add_argument("--arm-only", action="store_true", help="Arm; no record")
    args = parser.parse_args(argv)
    smm_dir = Path(args.smm_dir)
    if args.arm_only:
        arm_close_cycle(smm_dir)
        return 0
    record_abandonment(smm_dir, args.detector, args.agent_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
