#!/usr/bin/env python3
"""The record a running sprint reviewer leaves behind, and how to read it.

The harness backgrounds Agent-tool subagents, so a gate that clears on the
event the reviewer emits when it FINISHES cannot tell "running right now" from
"never invoked". This owns the evidence separating them, BOUNDED rather than
believed: passing forever on "it started" trades a nagging gate for a review
that is never run and never mentioned. Two states, not the three
`housekeeping_flight` reports — a stale record and no record leave the same
honest instruction. Duplicated rather than generalised; extract the shared
age/bounds logic if a third record appears.
"""

import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
import markers
import session_markers

# How long a started reviewer is believed to still be working: longer than the
# housekeeping window (a review reads a whole sprint's events and rewrites
# milestone delivery), far shorter than `hook_liveness`'s hours (that asks if
# the runtime is alive, this if one subagent still is). Too short re-fires the
# gate mid-review; too long delays it. Observe a longer review, raise this.
STALE_AFTER_SECONDS = 15 * 60

_STARTED_AT = "started_at"


def marker(session_id: object) -> markers.MarkerDef:
    """The in-flight record THIS session owns — session-keyed because the SMM
    is shared, so a neighbour's record would otherwise read as ours."""
    return session_markers.session_marker(
        marker_names.SPRINT_REVIEW_IN_FLIGHT, session_id
    )


def record_start(smm_dir: Path, input_data: dict) -> None:
    """Note that a reviewer started, so the gate can stop saying it did not.

    Never raises: this runs from a hook injector with no top-level guard, and
    recording the start must not be what stops it starting. A dropped record
    reads as "never invoked", which fails closed; the trace tells them apart.
    """
    import _common

    try:
        markers.marker_write(
            smm_dir,
            marker(input_data.get("session_id")),
            {
                "session_id": input_data.get("session_id"),
                _STARTED_AT: time.time(),
            },
        )
    except (ValueError, OSError, TypeError) as exc:
        _common.log_hook_error(
            f"sprint review in-flight record dropped: {exc}",
            error_class=type(exc).__name__,
        )


def is_fresh(smm_dir: Path, input_data: dict, now: float | None = None) -> bool:
    """Is a reviewer for THIS session inside its window right now?

    Unreadable, unageable and out-of-window all answer False: none of them
    proves a review is running. Bounded at BOTH ends — a future timestamp ages
    negative, and an upper bound alone would read that as fresh for the rest of
    the session, suppressing the gate in silence. Milliseconds where seconds
    were meant is the cheapest way to produce one.
    """
    record = markers.marker_read(smm_dir, marker(input_data.get("session_id")))
    if not isinstance(record, dict):
        return False
    age = session_markers.marker_age_seconds(
        time.time() if now is None else now, record.get(_STARTED_AT)
    )
    return age is not None and 0 <= age < STALE_AFTER_SECONDS


def sweep_orphan_records(smm_dir: Path, now: float | None = None) -> None:
    """Delete records no session can still be reviewing under.

    Called from the SessionStart sweep, which is why FRESHNESS is checked and
    not just the name: the glob spans a shared SMM, and another window's
    reviewer may be running behind one of these. Same rule, same reason, as
    `housekeeping_flight.sweep_orphan_records`. Never raises.
    """
    stamp = time.time() if now is None else now
    for path in smm_dir.glob(f"{marker_names.SPRINT_REVIEW_IN_FLIGHT}*"):
        if path.is_symlink():
            continue
        record = markers.marker_read(smm_dir, markers.MarkerDef(path.name, "json"))
        age = (
            session_markers.marker_age_seconds(stamp, record.get(_STARTED_AT))
            if isinstance(record, dict)
            else None
        )
        if age is not None and 0 <= age < STALE_AFTER_SECONDS:
            continue
        with contextlib.suppress(OSError):
            path.unlink()


def consume(smm_dir: Path, input_data: dict) -> str | dict | None:
    """Retire this session's record when the run ends, successfully or not.

    One that outlived its run would suppress a gate whose sprint_end never came.
    """
    return markers.marker_consume(smm_dir, marker(input_data.get("session_id")))
