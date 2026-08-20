#!/usr/bin/env python3
"""Hook-liveness heartbeat: the marker a running hook leaves behind.

When the runtime stops enforcing, its gates vanish and the session looks normal.

There is no VERDICT here any more. A reader once turned this marker into a
live/not-live answer and a preload refused on it, but that reader was reachable
only from the injection hook — so it judged a runtime already running — and the
handler wrote the heartbeat immediately before the preload read it. Inert by
construction, so story-009 deleted it rather than reordering the write.

What remains is the primitive: the write helper, the session-id candidate
chain, and the marker naming. Its consumers ask about OTHER sessions, which is
the question the deleted reader could never answer —
`coordination._session_is_live` for the Stop gates' conflict check, and
`close_cycle_abandonment.owner_session_is_live` for whether a close cycle's
owner is still running. Both answer `bool | None` and treat an unageable
heartbeat as "cannot tell"; anything added here should keep that shape.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import hook_heartbeat_scan
import marker_names
import markers
import plugin_loader
import session_markers
import session_scope

# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

# Session id is the PRIMARY signal. The time leg below is a weak backstop and
# must not be mistaken for the guarantee: only an id comparison can tell a
# session where hooks ran from one where they silently did not.
#
# Ordered candidates, but order only breaks ties between values that AGREE —
# disagreement refuses (see `resolve_session_id`). A second host is a new entry,
# not a redesign — but the entry goes in `smm/session_scope.py`, which is where the
# chain now lives: session-scoped marker filenames resolve the same chain from
# the appender's pre-write path, and that path cannot import `scripts/`. Two
# copies would let a new host be taught to the heartbeat while every scoped
# marker silently degraded to its shared name. Re-exported here because callers
# and tests address it through this module.
SESSION_ID_ENV_CANDIDATES: tuple[str, ...] = session_scope.SESSION_ID_ENV_CANDIDATES

# The freshness window. Owned by `hook_heartbeat_scan`, which is where the
# scans that enforce it live; re-exported here, like the candidate chain above,
# because callers and tests address the threshold through this module. One
# object, not two that agree by coincidence.
STALE_AFTER_SECONDS = hook_heartbeat_scan.STALE_AFTER_SECONDS
FUTURE_SKEW_GRACE_SECONDS = hook_heartbeat_scan.FUTURE_SKEW_GRACE_SECONDS

# ---------------------------------------------------------------------------
# Session id
# ---------------------------------------------------------------------------


def resolve_session_id() -> str | None:
    """The one session id the candidate chain agrees on, else None.

    NOT "the first non-empty candidate": candidates that DISAGREE resolve to
    None as well, because which one a host owns depends on which process
    launched which — runtime state the environment does not record. Order
    only picks among values that already agree.

    None therefore covers two different claims, and a caller whose verdict can
    be positive must split them with `session_scope.conflicting_session_ids`
    before acting. No shipped caller does today — the one that did was the
    verdict reader, deleted with the rest of that machinery — so the helper is
    named here for whoever needs it next rather than left implied.

    With no candidate set at all, the check falls back to the shared,
    unsuffixed marker and ages THAT — a host whose hooks are handed no id write
    and read that same one marker, so it is never bricked for want of a
    variable name. It does not fall back to time alone: another session's
    fresh heartbeat is evidence about that session, and accepting it let an
    unenforced session report live.

    That no-brick guarantee needs writer and reader to see the SAME absence. A
    host that hands its hooks a payload id while exposing none to a shell writes
    suffixed markers no shell reader can address, so every one of its preloads
    refuses — fixed by teaching this chain that host's variable, or by handing
    the reader a payload of its own, never by restoring the borrow.

    Delegates to `session_scope`, which owns the chain: the same resolution
    picks the filename of every session-scoped marker, and one of those is
    read from the appender's pre-write path.
    """
    return session_scope.resolve_session_id()


def payload_session_id(input_data: dict) -> str | None:
    """The session id a hook was handed, normalised for `write_heartbeat`.

    `write_heartbeat` consults the candidate chain only for None. An empty
    string or a non-str id would skip that fallback and key a marker on the
    hash of a value no reader ever addresses — a heartbeat that exists on disk
    and is invisible to every check, which is worse than none at all because
    it also silences the reaper. Both normalise to None here.

    Lives beside the primitive it feeds rather than in the hooks that call it:
    the rule is a property of `write_heartbeat`'s contract, not of any one
    hook, so every future writer gets the same normalisation instead of
    re-deriving it. Takes the raw hook payload for the same reason
    `identity.resolve_agent_id` does — that shape is the common currency.
    """
    raw = input_data.get("session_id")
    return (raw.strip() or None) if isinstance(raw, str) else None


def heartbeat_marker(session_id: str | None) -> markers.MarkerDef:
    """The heartbeat this session owns.

    `session_markers.session_marker` owns the naming rule — hash the
    untrusted id rather than sanitise it, and resolve no-id to the unsuffixed
    shared marker, which the reaping glob deliberately does not match. Shared
    with the housekeeping in-flight record, the only other session-keyed
    marker.
    """
    return session_markers.session_marker(marker_names.HOOK_HEARTBEAT, session_id)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_heartbeat(
    smm_dir: Path, *, session_id: str | None = None, now: float | None = None
) -> None:
    """Record that a hook ran. Called only from inside the hook runtime.

    `session_id` defaults to the candidate chain, but a hook that was handed
    one in its own input should pass it: that is the runtime's own answer
    rather than an inference from the environment.

    Never raises. `marker_write` rejects a symlinked marker with ValueError
    and a full or read-only SMM with OSError, and this is called from hook
    entry points that have no top-level guard — recording liveness must not
    be the thing that breaks the hook whose liveness it records. Same
    contract as `_common.append_safe` and `markers.warn_once`.

    The drop is logged, never silent. A heartbeat that never lands reads
    downstream as "the hook runtime is not running", which is a false alarm
    rather than a dangerous one — it fails closed. The `hook_errors.jsonl`
    trace is what tells the two apart.
    """
    # Lazy, matching markers.warn_once: hooks import this module on every
    # invocation, and the error path is the exception rather than the rule.
    import _common

    if session_id is None:
        session_id = resolve_session_id()
    stamp = time.time() if now is None else now
    marker = heartbeat_marker(session_id)
    try:
        markers.marker_write(
            smm_dir,
            marker,
            {
                "session_id": session_id,
                "plugin_version": plugin_loader.plugin_version(),
                "written_at": stamp,
            },
        )
    except (ValueError, OSError) as exc:
        _common.log_hook_error(
            f"write_heartbeat dropped: {exc}",
            error_class=type(exc).__name__,
        )
        return
    hook_heartbeat_scan.reap_stale_siblings(
        smm_dir, markers.marker_path(smm_dir, marker), stamp
    )
