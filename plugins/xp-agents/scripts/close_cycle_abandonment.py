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
  - the close preloads — a new close is arming over a survivor, which proves
    the previous cycle is over.

They share one content and one budget owner here because two hand-rolled
constructions would drift, and only one of them would be budget-pinned: an
over-budget concern is dropped by `append_safe`, which is a real prior outage
on this exact record. `metadata.detector` is what tells the three apart in the
log.

No double-record risk by construction: recording CONSUMES the marker, so a
cycle recorded by one detector is invisible to the next.

Degrades quiet. Every caller is a cleanup path — a hook, a sweep, a preload —
and none of them may fail a session because an append failed. The consume runs
either way, so a failed record can never strand the marker it was reporting.
"""

import contextlib
import os
import sys
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


def record_abandonment(smm_dir: Path, detector: str, agent_id: str = "") -> bool:
    """Record the abandonment concern, then consume the marker.

    Returns True when a record was made. An ABSENT marker records nothing and
    returns False — that is the normal case on every path that calls this, and
    recording there would turn a real signal into a per-session tax nobody
    reads.

    `agent_id` defaults to the cwd-derived id, the same resolution every
    skill-invoked script without hook input uses.
    """
    if detector not in DETECTORS:
        raise ValueError(f"unknown detector {detector!r}; expected one of {DETECTORS}")
    if not markers.marker_exists(smm_dir, markers.CLOSE_CYCLE_ACTIVE):
        return False

    # Suppressed, not ignored: `append_safe` already logs its own drops to
    # hook_errors.jsonl, and anything it raises past that must not take down a
    # cleanup path. The consume below is deliberately OUTSIDE the guard.
    with contextlib.suppress(Exception):
        _common.append_safe(
            smm_dir,
            _common.make_event(
                _common.CONCERN,
                agent_id or identity.resolve_agent_id_from_cwd(os.getcwd()),
                CONCERN_CONTENT,
                severity="high",
                metadata={
                    "kind": event_schema.CONCERN_KIND_CLOSE_CYCLE_BYPASS,
                    "detector": detector,
                },
            ),
        )
    markers.marker_consume(smm_dir, markers.CLOSE_CYCLE_ACTIVE)
    return True


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
