#!/usr/bin/env python3
"""The record a running housekeeper leaves behind, and how to read it.

The harness backgrounds Agent-tool subagents, so "the housekeeper is running
right now" is invisible to anything that only looks at the need marker: it
reads identically to "nobody ever invoked it". The Stop gate then tells the
lead to invoke an agent already in flight, and the only way to satisfy it is
to busy-wait instead of ending the turn.

This module owns the evidence that tells those two apart — the marker name,
the record shape, the write, the freshness window, and the did-it-actually-
finish predicate. One module rather than four, because the record's keys are
an implicit contract between the hook that writes it (SubagentStart), the gate
that reads it (Stop), and the hook that retires it (SubagentStop); spelled out
as string literals in three scripts, a rename would fail quietly. Same shape
of concern as `hook_liveness`, and it gets the same treatment.

In-flight is BOUNDED, not believed. Passing forever on "it started" would
trade a nagging gate for a silent skip — a dead housekeeper would mean
curation never happens and nothing ever says so. Past the window the gate
blocks again, with different wording, and the lead re-invokes.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
import markers

# How long a started housekeeper is believed to still be working.
#
# Short on purpose, and deliberately NOT shared with `hook_liveness`'s 4-hour
# threshold: that one asks "is the hook runtime alive across an idle session",
# this one asks "is this one subagent still working". Opposite tolerances for
# a false refusal, so one shared window would fail both.
#
# The cost, stated plainly: a housekeeper slower than this reads stale and the
# lead re-invokes needlessly. That fails CLOSED, which is the right direction.
STALE_AFTER_SECONDS = 10 * 60

# The three states the evidence can be in. Strings rather than a bool-plus-None
# tri-state so the caller's mapping reads as three named cases.
FRESH = "fresh"
STALE = "stale"
ABSENT = "absent"

_STARTED_AT = "started_at"
_WATERMARK = "curation_watermark"


def marker(session_id: object) -> markers.MarkerDef:
    """The in-flight record THIS session owns.

    Keyed per session because the SMM is deliberately shared: spawners export
    SMM_DIR verbatim to their teammates, and two windows on one repo resolve
    the same project id. An SMM-global record left by another session would
    read as this one's, and the gate would pass on someone else's work.

    `markers.session_marker` owns the naming rule (hash an untrusted id rather
    than sanitise it; no id means the shared marker) — the same rule the hook
    liveness heartbeat is named by. What is local here is only WHICH base name.
    """
    return markers.session_marker(marker_names.HOUSEKEEPING_IN_FLIGHT, session_id)


def record_start(smm_dir: Path, input_data: dict) -> None:
    """Note that a housekeeper started, so the gate can stop saying it didn't.

    Also snapshots the curation watermark. `complete-curation` is the
    housekeeper's mandatory finalize step and it rewrites that watermark, so
    comparing the snapshot against it at SubagentStop is an observable proxy
    for "this run actually curated" — the SubagentStop payload carries no
    success or status field to gate on.

    Never raises. `marker_write` rejects a symlinked marker and a read-only
    SMM, and this is called from a hook injector with no top-level guard:
    recording that the housekeeper started must not be the thing that stops it
    starting. A dropped record reads downstream as "never invoked", which
    fails closed; the `hook_errors.jsonl` trace is what tells the two apart.
    """
    import _common
    import materialize

    try:
        markers.marker_write(
            smm_dir,
            marker(input_data.get("session_id")),
            {
                "session_id": input_data.get("session_id"),
                _STARTED_AT: time.time(),
                _WATERMARK: materialize.read_curation_watermark(smm_dir)["timestamp"],
            },
        )
    except (ValueError, OSError, TypeError) as exc:
        _common.log_hook_error(
            f"housekeeping in-flight record dropped: {exc}",
            error_class=type(exc).__name__,
        )


def state(smm_dir: Path, input_data: dict, now: float | None = None) -> str:
    """FRESH, STALE or ABSENT for this session's record.

    A record whose timestamp cannot be aged (missing, non-numeric, boolean,
    non-finite) is STALE rather than ABSENT: something DID start, we simply
    cannot tell how long ago, and the honest verdict is "re-invoke it".

    Corrupt JSON is different. `marker_read` collapses it to None, which lands
    on ABSENT, because a record we cannot parse tells us nothing about whether
    one was ever written.

    The window is bounded at BOTH ends. A timestamp in the future ages
    negative, and `age < STALE_AFTER_SECONDS` alone would call that fresh
    forever — the gate would pass every turn for the rest of the session and
    curation would be skipped in silence, which is the failure this module
    exists to prevent. A millisecond timestamp where seconds were meant is the
    cheapest way to get there; a clock stepping backwards is the other. Neither
    is a record we can age, so both are STALE.
    """
    record = markers.marker_read(smm_dir, marker(input_data.get("session_id")))
    if not isinstance(record, dict):
        return ABSENT
    age = markers.marker_age_seconds(
        time.time() if now is None else now, record.get(_STARTED_AT)
    )
    if age is not None and 0 <= age < STALE_AFTER_SECONDS:
        return FRESH
    return STALE


def consume(smm_dir: Path, input_data: dict) -> str | dict | None:
    """Retire this session's record and hand back what it held.

    Always called when the run ends, successfully or not: a record that
    outlived its run would make the next Stop report a stall about a
    housekeeper that is already gone.
    """
    return markers.marker_consume(smm_dir, marker(input_data.get("session_id")))


def finalized(smm_dir: Path, record: object) -> bool:
    """Did the run this record belongs to actually finish its curation?

    SubagentStop fires whether the subagent finished or died, and its payload
    carries no success, status or error field to gate on — confirmed by
    capturing a real payload, not by reading the docs. Without a check, a
    crashed housekeeper consumes the need without curating: the silent skip
    this gate exists to prevent, arriving through a different door.

    So compare the artifact instead. A curation watermark that has not moved
    since the snapshot means `complete-curation` never ran.

    No record means no reference point — the write was dropped, or
    SubagentStart never fired. That degrades to the pre-existing behaviour
    (treat as done) rather than latching the need on forever: refusing on a
    comparison we cannot make would be a livelock the lead has no way out of.
    """
    import materialize

    if not isinstance(record, dict) or _WATERMARK not in record:
        return True
    return (
        materialize.read_curation_watermark(smm_dir)["timestamp"] != record[_WATERMARK]
    )
