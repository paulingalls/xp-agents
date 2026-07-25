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

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markers
import plugin_loader

# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

# Session id is the PRIMARY signal. The time leg below is a weak backstop and
# must not be mistaken for the guarantee: only an id comparison can tell a
# session where hooks ran from one where they silently did not.
#
# Ordered candidates, first non-empty wins. A second host is a new entry here,
# not a redesign. Own-variable first so a host we do not yet know about can be
# taught by exporting one value.
SESSION_ID_ENV_CANDIDATES: tuple[str, ...] = (
    "XP_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
)

# How long a heartbeat stays trustworthy. Four hours is deliberately loose:
# it must never refuse a user who stepped away between prompts, because a
# check that false-refuses is a check people switch off.
#
# Be honest about what that costs. With session-id matching carrying the
# precision, this leg's only remaining job is catching a runtime that dies
# MID-session, and at four hours it will not catch that quickly. Tightening
# it needs a refresh source with a higher frequency than one-per-prompt.
STALE_AFTER_SECONDS = 4 * 60 * 60

CODE_LIVE = "live"
CODE_NO_MARKER = "no-marker"
CODE_SESSION_MISMATCH = "session-mismatch"
CODE_STALE = "stale"
CODE_UNREADABLE = "unreadable"

# Codes meaning "could not determine" rather than "determined not live". Both
# refuse — a check that cannot see is not a check that passed — but only the
# determined ones support a diagnosis, so callers phrase them differently.
UNDETERMINED_CODES = frozenset({CODE_UNREADABLE})


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


# ---------------------------------------------------------------------------
# Session id
# ---------------------------------------------------------------------------


def resolve_session_id() -> str | None:
    """First non-empty session id in the candidate chain, else None.

    None means "no id is discoverable here", not "no session" — the
    predicate degrades to a time-only check rather than refusing, so an
    unfamiliar host is never bricked for want of a variable name.
    """
    for name in SESSION_ID_ENV_CANDIDATES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _plugin_version() -> str:
    """Version of the plugin whose hook wrote the heartbeat.

    Duplicated from session_start's private reader rather than imported: a
    library module must not import a hook entry point, and the hooks that
    call this one will import this module.
    """
    try:
        path = plugin_loader.resolve_plugin_root() / ".claude-plugin" / "plugin.json"
        return str(json.loads(path.read_text(encoding="utf-8")).get("version", "?"))
    except (OSError, json.JSONDecodeError, ValueError):
        return "?"


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
    """
    if session_id is None:
        session_id = resolve_session_id()
    markers.marker_write(
        smm_dir,
        markers.HOOK_HEARTBEAT,
        {
            "session_id": session_id,
            "plugin_version": _plugin_version(),
            "written_at": time.time() if now is None else now,
        },
    )


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


def _describe(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def check_liveness(smm_dir: Path, *, now: float | None = None) -> Liveness:
    """Report whether the hook runtime is live for the calling session.

    live = (the session id matches the heartbeat's, OR no id is
            discoverable) AND the heartbeat is younger than the threshold.
    """
    now = time.time() if now is None else now
    path = markers.marker_path(smm_dir, markers.HOOK_HEARTBEAT)
    data = markers.marker_read(smm_dir, markers.HOOK_HEARTBEAT)
    if not isinstance(data, dict):
        # `marker_read` collapses missing, symlinked and corrupt into None.
        # Anything present-but-unreadable is a different claim from nothing
        # ever having been written, so split them back apart here.
        if path.is_symlink() or path.exists():
            return Liveness(False, _UNREADABLE_REASON, CODE_UNREADABLE)
        return Liveness(
            False,
            f"No hook-liveness heartbeat has been recorded. {_NOT_LOADED}",
            CODE_NO_MARKER,
        )

    written_at = data.get("written_at")
    if not isinstance(written_at, (int, float)) or isinstance(written_at, bool):
        return Liveness(False, _UNREADABLE_REASON, CODE_UNREADABLE)
    age = now - float(written_at)
    session_id = resolve_session_id()
    if session_id is not None and data.get("session_id") != session_id:
        return Liveness(
            False,
            f"The last hook-liveness heartbeat ({_describe(age)} old) belongs "
            f"to a different session, so no hook has run in this one. "
            f"{_NOT_LOADED}",
            CODE_SESSION_MISMATCH,
        )
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
