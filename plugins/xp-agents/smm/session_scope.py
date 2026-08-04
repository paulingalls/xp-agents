#!/usr/bin/env python3
"""Session scoping for marker filenames — reachable from BOTH sys.path halves.

A marker that two concurrent sessions must not share folds its session id
into its filename. That rule lives here, in `smm/`, rather than beside the
marker infrastructure in `scripts/session_markers.py`, because its two users
sit on opposite sides of the sys.path boundary:

- `scripts/markers.py` builds session-scoped `MarkerDef`s from it, and
  `scripts/session_markers.session_marker` builds the heartbeat's on top of
  `scoped_name` — so there is ONE hashing rule, not two that agree by
  coincidence.
- `smm/_append_impl.py` resolves the same filename in its PRE-WRITE path to
  read the close-cycle id off disk, and that path must not import `scripts/`.

Only `smm/` is importable from both, so this is the one home they can share.

The env candidate chain lives here for the same reason: `hook_liveness`
imports it from here rather than restating it, so teaching the plugin a new
host variable cannot leave a session-scoped marker silently degrading to the
shared name while the heartbeat follows the new host.
"""

import os

# Session id candidates, ordered — first non-empty wins. A new host is a new
# entry here, not a redesign. Own-variable first so a host we do not yet know
# about can be taught by exporting one value.
#
# Read by `hook_liveness.resolve_session_id` (which re-exports this tuple) and
# by every session-scoped marker's filename. tests/_env_hygiene.py pins the
# first and strips the rest for the whole suite.
#
# Order after the first is by OWNERSHIP, not arrival: a host launched from
# another agent inherits that agent's variable, so several can be set at once
# and preference alone picks the heartbeat a preload addresses. Measured — a
# second-harness session carried the launching harness's id, resolved the
# LAUNCHER's heartbeat, found none and withheld every skill's context while its
# own hooks were running fine. So the more-derived host ranks higher, and the
# one that leaks downward ranks last.
SESSION_ID_ENV_CANDIDATES: tuple[str, ...] = (
    "XP_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDE_CODE_SESSION_ID",
)


def resolve_session_id() -> str | None:
    """First non-empty session id in the candidate chain, else None.

    None means "no id is discoverable here", not "no session" — callers
    degrade rather than refuse, so an unfamiliar host is never bricked for
    want of a variable name.

    Deliberately NOT memoised: the result depends on `os.environ`, and a
    cached env-derived value breaks test isolation in a source-order runner
    (see CLAUDE.md's test-isolation gotcha).
    """
    for name in SESSION_ID_ENV_CANDIDATES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def scoped_name(base_name: str, session_id: object) -> str:
    """The marker filename one session owns, or the shared one with no id.

    A session id is untrusted input that would otherwise steer a path, so it
    is hashed rather than sanitised — there is no escaping rule to get wrong.
    Anything that is not a non-blank string resolves to the unsuffixed shared
    name: the check such a host was always going to get, rather than a file
    keyed on the hash of a value no reader addresses, invisible to every
    check and outliving the sweep that reaps suffixed siblings.

    `hashlib` is imported lazily because every hook loads this module (via
    `markers`), it pulls in a C extension (~3ms cold), and only the scoped
    markers need it.
    """
    import hashlib

    if isinstance(session_id, str) and session_id.strip():
        digest = hashlib.sha256(session_id.strip().encode("utf-8")).hexdigest()[:12]
        return f"{base_name}-{digest}"
    return base_name
