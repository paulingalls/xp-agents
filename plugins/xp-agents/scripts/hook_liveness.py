#!/usr/bin/env python3
"""Hook-liveness heartbeat: the marker a running hook leaves behind.

When the hook runtime fails to load, every gate it enforces disappears and
the session looks normal. The check that would say so has nowhere to run —
it would itself be a hook. A marker that could only have been written BY a
hook, read by an instruction-time preload, breaks that circle: the preload
still executes when the thing it tests is broken.

This module is the primitive only — the write helper, the session-id
candidate chain, the staleness predicate, and a thin CLI. The hooks that
refresh the marker and the preload that consumes the verdict live
elsewhere.
"""

import sys
import time
from dataclasses import dataclass
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
# Ordered candidates, first non-empty wins. A second host is a new entry, not a
# redesign — but the entry goes in `smm/session_scope.py`, which is where the
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

CODE_ID_CONFLICT = "id-conflict"
CODE_LIVE = "live"
CODE_NO_MARKER = "no-marker"
CODE_SESSION_MISMATCH = "session-mismatch"
CODE_STALE = "stale"
CODE_UNREADABLE = "unreadable"

# Codes meaning "could not determine" rather than "determined not live". Both
# refuse — a check that cannot see is not a check that passed — but only the
# determined ones support a diagnosis, so callers phrase them differently.
# A conflict belongs here, not with the determined ones: nothing was learned
# about the runtime: only that we cannot say whose session this is. It carries a
# diagnosis anyway because the fix is known even when the verdict is not.
UNDETERMINED_CODES = frozenset({CODE_UNREADABLE, CODE_ID_CONFLICT})

# Exit statuses for the CLI. This tool fails CLOSED: only a positive verdict
# exits zero. 2 is skipped because argparse spends it on usage errors, and a
# mistyped invocation must not be mistaken for a liveness answer.
EXIT_LIVE = 0
EXIT_NOT_LIVE = 1
EXIT_UNDETERMINED = 3


@dataclass(frozen=True, slots=True)
class Liveness:
    """A liveness verdict plus the sentence a caller should print.

    `code` is the stable machine token callers branch on; `reason` is prose
    for a human. Callers must never branch on `reason` — its wording is
    free to change.
    """

    live: bool
    reason: str
    code: str


_NOT_LOADED = (
    "The hook runtime is not running: the plugin providing it is likely "
    "not loaded, disabled, or registered under a path that no longer exists."
)

_UNREADABLE_REASON = (
    "A hook-liveness heartbeat exists but cannot be read — it is corrupt, or "
    "it has been replaced by a link. Whether the hook runtime is running "
    "cannot be determined, so it must not be assumed."
)


def _conflict_reason(names: tuple[str, ...]) -> str:
    """Refusal prose. Why the remedy is SUBTRACTIVE: `resolve_session_id`."""
    return (
        f"Two session-id variables disagree ({', '.join(names)}), so which "
        "session this process belongs to cannot be determined — one was "
        "inherited from an agent that launched this one, and whether the hook "
        "runtime is running HERE must not be assumed. Unset the variable this "
        "session does not own, before launching it, so a single id is left; "
        "setting XP_SESSION_ID too adds a third disagreement, not a tie-break."
    )


# ---------------------------------------------------------------------------
# Session id
# ---------------------------------------------------------------------------


def resolve_session_id() -> str | None:
    """First non-empty session id in the candidate chain, else None.

    None means "no id is discoverable here", not "no session" — the
    predicate degrades to a time-only check rather than refusing, so an
    unfamiliar host is never bricked for want of a variable name.

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


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


def _describe(seconds: float) -> str:
    # Clamped: an age inside the skew grace can be slightly negative, and
    # "last heartbeat -3s ago" reads as a bug in the report.
    seconds = max(seconds, 0.0)
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def _live_on_freshness_alone(age: float) -> Liveness:
    return Liveness(
        True,
        f"Hook runtime is live (last heartbeat {_describe(age)} ago; no "
        "session id available here, so freshness is the only signal).",
        CODE_LIVE,
    )


def _no_heartbeat_of_our_own(
    smm_dir: Path, session_id: str | None, now: float
) -> Liveness:
    """Verdict when this session's own heartbeat is missing.

    With an id, two different problems wear the same absence. A fresh
    heartbeat from another session proves the runtime works on this machine
    and against this SMM — it just is not running for us, which points at
    trust or a per-session load failure rather than a missing plugin. Nothing
    fresh anywhere means nothing has run at all. Same refusal, different fix,
    so they get different messages.

    WITHOUT an id the two cannot be told apart, and guessing would be the
    wrong way round: a hook that was handed a session id in its payload
    writes a per-session file even when the reader's environment exposes no
    id, so demanding the shared marker would refuse a session whose hooks are
    demonstrably running. Degrading to time-only means exactly this — any
    fresh heartbeat counts.
    """
    freshest = hook_heartbeat_scan.freshest_sibling(smm_dir, now)
    if freshest is None:
        return Liveness(
            False,
            f"No hook-liveness heartbeat has been recorded. {_NOT_LOADED}",
            CODE_NO_MARKER,
        )
    if session_id is None:
        return _live_on_freshness_alone(freshest)
    return Liveness(
        False,
        "No hook has run in this session, though another session's hooks ran "
        f"{_describe(freshest)} ago. The runtime is reachable but not active "
        "here — its hooks are likely untrusted, or failed to load for this "
        "session.",
        CODE_SESSION_MISMATCH,
    )


def check_liveness(smm_dir: Path, *, now: float | None = None) -> Liveness:
    """Report whether the hook runtime is live for the calling session.

    live = (the session id matches the heartbeat's, OR no id is
            discoverable) AND the heartbeat is younger than the threshold.
    """
    now = time.time() if now is None else now
    conflict = session_scope.conflicting_session_ids()
    if conflict:
        # Must precede every path below, because all of them treat a None id as
        # "degrade to time-only, any fresh heartbeat counts". Under a conflict
        # the launcher's heartbeat IS fresh, so degrading would report live for
        # a session whose own hooks never ran — inverting this check rather than
        # weakening it. Unresolvable identity refuses, like the rest of the
        # gates here.
        return Liveness(False, _conflict_reason(conflict), CODE_ID_CONFLICT)
    session_id = resolve_session_id()
    marker = heartbeat_marker(session_id)
    path = markers.marker_path(smm_dir, marker)
    data = markers.marker_read(smm_dir, marker)
    if not isinstance(data, dict):
        # `marker_read` collapses missing, symlinked and corrupt into None.
        # Anything present-but-unreadable is a different claim from nothing
        # ever having been written, so split them back apart here.
        if path.is_symlink() or path.exists():
            return Liveness(False, _UNREADABLE_REASON, CODE_UNREADABLE)
        return _no_heartbeat_of_our_own(smm_dir, session_id, now)

    age = session_markers.marker_age_seconds(now, data.get("written_at"))
    if age is None or age < -FUTURE_SKEW_GRACE_SECONDS:
        # A timestamp that far ahead of us is not a heartbeat we can age, so it
        # is the same claim as a corrupt one: present, unreadable, no verdict.
        # Left alone it would read as fresh forever (see the constant).
        return Liveness(False, _UNREADABLE_REASON, CODE_UNREADABLE)
    if age >= STALE_AFTER_SECONDS and session_id is None:
        # A stale SHARED marker is not the last word when we cannot name our
        # own heartbeat: a hook handed a payload id writes a per-session file
        # this reader can never address, so the shared one goes stale while
        # hooks are demonstrably running. Same argument the absent path makes;
        # it applied to both branches, and only one of them had it.
        #
        # Only the LIVE half is borrowed. Falling through to the absent-path
        # verdict would report "no heartbeat has been recorded" about a
        # heartbeat that plainly was — staleness keeps its own diagnosis.
        fresh = hook_heartbeat_scan.freshest_sibling(smm_dir, now)
        if fresh is not None:
            return _live_on_freshness_alone(fresh)
    if age >= STALE_AFTER_SECONDS:
        return Liveness(
            False,
            f"The last hook-liveness heartbeat is {_describe(age)} old, past "
            f"the {_describe(STALE_AFTER_SECONDS)} threshold: the hook runtime "
            f"appears to have stopped partway through this session.",
            CODE_STALE,
        )
    return Liveness(
        True,
        f"Hook runtime is live (last heartbeat {_describe(age)} ago).",
        CODE_LIVE,
    )


# ---------------------------------------------------------------------------
# CLI: status
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # Lazy import: the hooks that refresh the heartbeat import this module on
    # every invocation, and argparse is needed only on the CLI path.
    import argparse

    parser = argparse.ArgumentParser(description="Hook-liveness heartbeat CLI")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "status", help="Print the liveness verdict; exit non-zero unless live"
    )
    args = parser.parse_args(argv)

    result = check_liveness(Path(args.smm_dir))
    print(result.reason)
    if result.live:
        return EXIT_LIVE
    return EXIT_UNDETERMINED if result.code in UNDETERMINED_CODES else EXIT_NOT_LIVE


if __name__ == "__main__":
    sys.exit(main())
