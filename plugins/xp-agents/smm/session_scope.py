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

# Session id candidates. A new host is a new entry here, not a redesign.
#
# Read by `hook_liveness.resolve_session_id` (which re-exports this tuple) and
# by every session-scoped marker's filename. tests/_env_hygiene.py pins the
# first and strips the rest for the whole suite.
#
# ORDER IS NOT LOAD-BEARING, and deliberately so. A host launched from another
# agent inherits that agent's variable, so two can be set at once — and which
# one this host OWNS depends on which launched which, runtime state that the
# environment does not record. Any fixed preference is therefore correct in one
# nesting direction and silently wrong in the mirrored one, so disagreement
# refuses instead (see `conflicting_session_ids`). Order only picks among values
# that already agree, where it cannot change the answer.
#
# Measured, and the reason this is not theoretical: a second-harness session
# carried the launching harness's id, resolved the LAUNCHER's heartbeat, and
# withheld every skill's context while its own hooks were running fine.
SESSION_ID_ENV_CANDIDATES: tuple[str, ...] = (
    "XP_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDE_CODE_SESSION_ID",
)


def conflicting_session_ids() -> tuple[str, ...]:
    """Candidate names holding DIFFERENT ids, or empty when there is one answer.

    Two set to the same value is one id under two names, not ambiguity — only
    disagreement is unresolvable. Returned in chain order so a caller can name
    them in a stable, reproducible sentence.
    """
    seen: dict[str, str] = {}
    for name in SESSION_ID_ENV_CANDIDATES:
        value = os.environ.get(name, "").strip()
        if value:
            seen[name] = value
    if len(set(seen.values())) < 2:
        return ()
    return tuple(seen)


def resolve_session_id() -> str | None:
    """The one discoverable session id, or None when there is not exactly one.

    None means "no id is addressable here", not "no session" — every caller
    falls back to the shared, unsuffixed marker name. Two shapes reach it, and
    they must NOT be collapsed by a caller whose verdict can be positive: no
    candidate set, and candidates that DISAGREE.

    No candidate set is a degradation. Nothing is being hidden, so a caller may
    fall back to the shared, unsuffixed marker rather than refuse, and an
    unfamiliar host is never bricked for want of a variable name. It does NOT
    license falling back to time alone: another session's fresh heartbeat is
    evidence about that session, and a liveness caller accepting it let a
    session enforcing nothing report live.

    Disagreement is a refusal, and returns None rather than a preference
    because picking wrong is worse than picking nothing. Hooks key their
    heartbeat on the id the host handed them, so the other id addresses the
    LAUNCHER's heartbeat — which reads as live when this session's hook runtime
    never loaded, a fail-open in the check built to catch precisely that.
    Degrading loses session scoping; guessing inverts the verdict. A caller
    that can answer "live" must therefore distinguish the two shapes via
    `conflicting_session_ids` before it degrades — the None alone cannot tell
    them apart. Callers that only NAME a marker need no such split: the shared
    name is the same safe answer either way.

    The only way to settle a disagreement is to leave exactly one candidate
    set. `XP_SESSION_ID` is a candidate like the rest, not an override, so
    exporting it alongside an inherited id adds a third disagreeing value.

    Deliberately NOT memoised: the result depends on `os.environ`, and a
    cached env-derived value breaks test isolation in a source-order runner
    (see CLAUDE.md's test-isolation gotcha).
    """
    if conflicting_session_ids():
        return None
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
