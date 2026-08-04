#!/usr/bin/env python3
"""Session-marker lifecycle: naming, aging, and the SessionStart sweep.

Extracted from markers.py to keep that module under its size pin. This
module owns the rule shared by session-keyed markers (liveness heartbeat,
housekeeping in-flight) and the sweep that clears markers which must never
survive a session boundary.
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
    CLOSE_CYCLE_ACTIVE,
    CLOSE_CYCLE_ID,
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

    This helper adds only the JSON content type, which is what the two
    session-keyed records here (liveness heartbeat, housekeeping in-flight)
    need: anything that is not a non-blank string resolves to the unsuffixed
    shared marker — the time-only check such a host was always going to get.
    """
    return MarkerDef(session_scope.scoped_name(base_name, session_id), "json")


def marker_age_seconds(now: float, written_at: object) -> float | None:
    """Age of a JSON marker's timestamp, or None when it is not usable.

    The single home for the rule, shared by `hook_liveness` and
    `housekeeping_flight`. Callers own the BOUNDS: a negative age (a future
    timestamp) comes back as-is, and BOTH callers bound it, because
    `age < threshold` alone reads a negative age as fresh forever. They differ
    only in how much future they tolerate first — the housekeeping gate none
    (`0 <= age`), the heartbeat a minute of clock slew
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

# Markers that should never survive across SessionStart. CLOSE_CYCLE_ACTIVE
# leaks when a close-skill aborts before the xp-close-reviewer fork; ACCEPT
# leaks after teammate-worktree close-cycle Edits when /xp-accept's
# no-reviewing-stories path skips the consume; ACCEPT_IN_FLIGHT leaks when
# /xp-accept is abandoned before its terminal dispatch (/xp-schedule or
# /xp-sprint-review completion, where accept_terminal drains it). This sweep
# is the abandonment backstop.
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
_STALE_SESSION_MARKERS: tuple[MarkerDef, ...] = (
    CLOSE_CYCLE_ACTIVE,
    CLOSE_CYCLE_ID,
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

    Every marker above is unconditionally consumed because none of them can
    belong to another LIVE session. The housekeeping in-flight record can: the
    SMM is shared across windows and worktrees, so its orphans are swept by
    `housekeeping_flight.sweep_orphan_records`, which keeps a record that is
    still inside its freshness window. That module owns the record's field
    names and its window, and imports this one — hence the lazy import, the
    same shape `markers.warn_once` uses to reach `concerns`.

    CLOSE_CYCLE_ACTIVE is RECORDED before it is consumed, and it alone. This
    sweep is the one component that positively knows a close cycle died — the
    reviewer that releases the marker never ran — so consuming it silently
    threw away the only evidence anyone would ever have. The other five leak
    for ordinary reasons and stay silent, and a marker that is ABSENT (the
    normal case, every session) records nothing: `record_abandonment` owns both
    conditions, and it never raises, so a failed append cannot break a session
    start.
    """
    import close_cycle_abandonment

    close_cycle_abandonment.record_abandonment(
        smm_dir, close_cycle_abandonment.DETECTOR_SESSION_SWEEP
    )

    for marker in _STALE_SESSION_MARKERS:
        marker_consume(smm_dir, marker)

    import housekeeping_flight

    housekeeping_flight.sweep_orphan_records(smm_dir)
