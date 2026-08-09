#!/usr/bin/env python3
"""Session-marker lifecycle: naming, aging, and the SessionStart sweep.

Extracted from markers.py to keep that module under its size pin. This
module owns the rule shared by session-keyed markers and the sweep that
clears markers which must never survive a session boundary.
"""

import math
import sys
from pathlib import Path

# Own both legs of the path, as every sibling under `scripts/` does: a module
# that leans on its importer having done it dies at import for the next hook
# that follows the convention, and a hook that cannot import cannot degrade
# gracefully to exit 0.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import session_scope
from markers import (
    ACCEPT,
    ACCEPT_IN_FLIGHT,
    CLOSE_CYCLE_ID,
    HOUSEKEEPING_ARMED,
    SISTER_TEST_LAYOUT_WARN,
    TEAMMATE_CONFIG,
    MarkerDef,
    marker_consume,
)


def session_marker(base_name: str, session_id: object) -> MarkerDef:
    """The JSON marker one session owns, or the shared one when it has no id.

    The naming rule itself is `session_scope.scoped_name` — a session id is
    untrusted input that would otherwise steer a path, so it is hashed rather
    than sanitised, and the raw id goes in the payload where the diagnostic
    survives. It lives in `smm/` because the close-cycle-id marker resolves the
    same rule from the appender's pre-write path, which cannot import
    `scripts/`; one home means the two cannot drift.

    This helper adds only the JSON content type, which is what every
    session-keyed record here needs: anything that is not a non-blank string
    resolves to the unsuffixed shared marker — the time-only check such a host
    was always going to get.
    """
    return MarkerDef(session_scope.scoped_name(base_name, session_id), "json")


def marker_age_seconds(now: float, written_at: object) -> float | None:
    """Age of a JSON marker's timestamp, or None when it is not usable.

    The single home for the rule. Callers own the BOUNDS: a negative age (a
    future timestamp) comes back as-is, so any caller that must fail CLOSED has
    to bound it below — `age < threshold` alone reads a negative age as fresh
    forever. They differ in how much future they tolerate — the in-flight gates
    none (`0 <= age`), the heartbeat a minute of clock slew
    (`hook_liveness.FUTURE_SKEW_GRACE_SECONDS`), since false-refusing a working
    session is the failure that gets a liveness check switched off.

    Three ways a JSON number gets past a bare isinstance check, and on a
    fail-CLOSED caller two of them fail OPEN: `bool` is an `int` subclass;
    `NaN` and `Infinity` are values `json.loads` accepts by default, and
    neither compares True against a staleness threshold, so a corrupt marker
    would read as fresh. An out-of-range int overflows the float conversion
    outright, which raises rather than returning a verdict. So None means
    "cannot age this", which every caller must treat as expired, not as young.
    """
    if not isinstance(written_at, (int, float)) or isinstance(written_at, bool):
        return None
    try:
        value = float(written_at)
    except OverflowError:
        return None
    if not math.isfinite(value):
        return None
    return now - value


# ---------------------------------------------------------------------------
# Session-start sweep
# ---------------------------------------------------------------------------

# Markers that should never survive across SessionStart. ACCEPT leaks after
# teammate-worktree close-cycle Edits when /xp-accept's no-reviewing-stories
# path skips the consume; ACCEPT_IN_FLIGHT leaks when /xp-accept is abandoned
# before its terminal dispatch (/xp-schedule or /xp-sprint-review completion,
# where accept_terminal drains it). This sweep is the abandonment backstop.
#
# CLOSE_CYCLE_ACTIVE is deliberately NOT in this set. It is the one marker here
# that CAN belong to a live session other than this one — it is not
# session-scoped, and the SMM is shared across windows and worktrees — so an
# unconditional consume silently disarms a close another window is still
# running, and (once the sweep started recording) files a high-severity
# abandonment concern against it, which that close's own Step 6 count then
# reads as a reason to abort. `close_cycle_abandonment.record_abandonment` owns
# it instead, on the same age rule the other two detectors use.
#
# CLOSE_CYCLE_ID is the one entry that is session-SCOPED, and it is here for a
# different reason from the rest. Scoping already stops a previous session's id
# being read by this one — its filename is unaddressable from here — but on a
# host that exposes no session id at all, both sessions resolve the SAME
# unsuffixed file, and a leaked id there is worse than no id: a later close
# mints a different one, so the gate would EXCLUDE the concerns tagged with the
# dead cycle. That shared file is what this sweeps. Another session's suffixed
# marker is untouched by construction (this consumes only the name our own
# environment resolves) and must be: it can belong to a teammate's close that
# is still running against this shared SMM.
#
# HOUSEKEEPING_ARMED is here for exactly the same reason, and only that reason.
# It records that this session already armed the housekeeping gate. Scoping
# already makes a previous session's record unaddressable on a host that exposes
# a session id, so there the consume is a no-op on our own not-yet-written name.
# On a host that exposes NONE, both sessions resolve the same unsuffixed file,
# and a leaked record there is worse than none: it suppresses the new session's
# curation offer permanently — the mirror of the bug the record was added to fix.
_STALE_SESSION_MARKERS: tuple[MarkerDef, ...] = (
    CLOSE_CYCLE_ID,
    HOUSEKEEPING_ARMED,
    ACCEPT,
    ACCEPT_IN_FLIGHT,
    SISTER_TEST_LAYOUT_WARN,
    TEAMMATE_CONFIG,
)


def sweep_stale_session_markers(smm_dir: Path) -> None:
    """Clear markers that should never survive across a session boundary.

    Caller must gate to fresh-start SessionStart sources only — resume
    and compact are mid-session continuations where these markers may
    be load-bearing for in-flight close-skills or pending /xp-accept.

    Every marker in the set above is unconditionally consumed because none of
    them can belong to another LIVE session. Three records here can, and none
    is in that set. Two are in-flight records — the housekeeper's and the
    sprint reviewer's — each swept by its own module's `sweep_orphan_records`,
    which keeps a record still inside its own freshness window. Those modules
    own the field names and the (different) windows, and import this one —
    hence the lazy imports, the shape `markers.warn_once` uses for `concerns`.

    The close-cycle marker is the third, and it is RECORDED rather than
    consumed. This sweep is one of the three components that can positively
    learn a close cycle died — the reviewer that releases the marker never ran
    — so deleting it silently threw away the only evidence anyone would ever
    have. `close_cycle_abandonment.record_abandonment` owns every condition:
    absent (the normal case, every session) and still young (a close running in
    another window, or in this one before a `/clear`) both record nothing and
    consume nothing. It never raises, so a failed append cannot break a session
    start.
    """
    import close_cycle_abandonment

    close_cycle_abandonment.record_abandonment(
        smm_dir, close_cycle_abandonment.DETECTOR_SESSION_SWEEP
    )

    for marker in _STALE_SESSION_MARKERS:
        marker_consume(smm_dir, marker)

    import housekeeping_flight
    import sprint_review_flight

    housekeeping_flight.sweep_orphan_records(smm_dir)
    sprint_review_flight.sweep_orphan_records(smm_dir)
