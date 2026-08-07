#!/usr/bin/env python3
"""The SessionStart systemMessage — the only channel the USER reads.

Extracted from session_start.py, which sat at its recorded 450+ band ceiling, so
adding the not-enforcing banner would have landed it at 499 of a 500 cap. The
Constraints pillar is explicit that fitting "just under 500" is the shape that
produced that debt four times, so the block moved rather than the ceiling.

Cohesive on its own terms, not merely convenient: everything here composes the
one string the user sees at session start — the enforcing banner, the kickoff
nudge, the at-risk-root advisory and its remedies, and the not-enforcing line.

`_is_fresh_start` moved with them because the banner needs it and importing it
back from session_start would make a cycle. session_start re-imports the names
it still uses, so `session_start._system_message` keeps resolving for the 16
existing test call sites — none of them had to change.

WHAT DOES NOT BELONG HERE: deciding whether enforcement is on. `main` performs
that validation once and passes the answer in. A second validation in this
module is exactly what let the user's line say "active" while the agent's
context said "disabled".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import migration_lock
import plugin_loader
import smm_dir_resolve


def _is_fresh_start(source: str) -> bool:
    """True when the SessionStart source represents a fresh start.

    ``startup`` is a brand-new session (kickoff_gate hard-blocks until
    /xp-kickoff runs); ``clear`` is a mid-session reset (nudge only).
    Both arm the KICKOFF marker. ``resume`` and ``compact`` are
    continuations of an in-flight session — re-running kickoff would
    redo work just done.
    """
    return source in ("startup", "clear")


_AT_RISK_PREFIX = (
    "NOTE: the shared mental model still lives under the host-managed plugin "
    "data root, which 'claude plugin uninstall' deletes by default."
)

# One per migration_lock.LockState arm, named for its REMEDY.
#
# "in-progress" (holder proved RUNNING) is the one state that must not name
# --confirm: guessing at a live holder is the automatic-breaker mistake this
# story exists to avoid. "stalled" (holder proved dead) is the one state that
# names --confirm directly. "blocked" covers both shapes that never
# self-release on their own (an unverifiable holder, and non-symlink residue)
# and points at the read-only report first, since liveness there was never
# established.
_FREE_ADVISORY = _AT_RISK_PREFIX + (
    " It relocates itself automatically, but only once no teammate worktree "
    "and no in-place teammate remain — check for a stale one whose branch "
    "never merged. Run 'python3 {tool}' to see what is holding it."
)

_STALLED_ADVISORY = _AT_RISK_PREFIX + (
    " A prior relocation is stalled — its lock's holder is no longer "
    "running. Run 'python3 {tool} --confirm' to clear it."
)

_IN_PROGRESS_ADVISORY = _AT_RISK_PREFIX + (
    " A relocation looks to be in progress — its lock's holder is running. "
    "Run 'python3 {tool}' to see who holds it before doing anything else."
)

_BLOCKED_ADVISORY = _AT_RISK_PREFIX + (
    " Its relocation lock is blocked and not automatically verifiable. Run "
    "'python3 {tool}' to see what is holding it, then rerun with --confirm "
    "to clear it."
)

# "unprobeable" must NOT borrow the free wording: relocation does not resolve
# itself here, and the reason it cannot be read is usually also the reason it
# cannot proceed (a root-owned destination from one sudo'd run).
_UNPROBEABLE_ADVISORY = _AT_RISK_PREFIX + (
    " Whether a relocation lock is present could not be determined — its "
    "destination is unreadable, which one 'sudo' run is enough to cause. "
    "Relocation stays blocked until that is fixed: check ownership of the "
    "destination, then run 'python3 {tool}' to inspect."
)


def _tool_path() -> Path:
    """Copy-pasteable path to the manual tool, resolved at message time.

    Not hardcoded: the plugin cache is versioned, so a literal path would
    name whichever release wrote it.
    """
    return plugin_loader.resolve_plugin_root() / "scripts" / "migrate_smm_root.py"


def _lock_advisory(state: migration_lock.LockState) -> str:
    """The at-risk-root advisory template for ``state``, named for its remedy.

    A ``match`` over the ``Literal`` ``LockState`` rather than a dict lookup
    with a ``None`` fallback: pyright's exhaustiveness check then catches a
    missed arm if a fifth state is ever added, instead of silently falling
    back to the "free" message.
    """
    match state:
        case "free":
            return _FREE_ADVISORY
        case "stalled":
            return _STALLED_ADVISORY
        case "in-progress":
            return _IN_PROGRESS_ADVISORY
        case "blocked":
            return _BLOCKED_ADVISORY
        case "unprobeable":
            return _UNPROBEABLE_ADVISORY


# The USER's line when the shared model could not be initialised. `hook_output`
# sends the context to the AGENT and this to the user, so the two were free to
# disagree — and did: the agent read `disabled` while this said `active` and
# invited /xp-kickoff, into the one session no gate could police. Says neither,
# names a cause true on any host, and avoids `inactive` too (the substring, and
# because the gates are absent rather than in a state).
_DISABLED_MESSAGE = (
    "XP agents (v{version}) NOT ENFORCING — the shared model could not be "
    "initialised, so none of its gates are running. Check the data root is "
    "writable and not a broken symlink, then start a new session."
)


def _disabled_message(version: str) -> str:
    """The banner for a session whose gates are absent."""
    return _DISABLED_MESSAGE.format(version=version)


def _system_message(source: str, version: str, smm_dir: Path | None = None) -> str:
    """SessionStart systemMessage for a session that IS enforcing.

    Enforcement state is decided by the caller and never re-derived here — see
    ``session_start.main``. A second validation in this function is what allowed
    the two channels to disagree, so `smm_dir=None` still means only "the path is
    unknown, do not guess one in the advisory", never "the gates are off".

    Kickoff nudge only on fresh starts.

    The at-risk-root advisory rides here rather than in additionalContext for
    two reasons. The USER is the one who has to act on it — the blocker is a
    directory only they can retire. And relocation can stay declined
    indefinitely: the liveness gate keys on a worktree directory existing, and
    nothing removes one whose branch never merged, so a release note is not a
    substitute. A line buried in a context blob is the silent-enforcement
    pattern this change exists to end.

    Known limit, not a bug: this only runs on the lead path (see
    ``session_start.main``) — a teammate's SMM_DIR is pinned at spawn and it
    cannot relocate anything, and relocation declines while any teammate is
    live, so only the lead session can act on what this says.
    """
    base = f"XP agents (v{version}) active."
    if _is_fresh_start(source):
        base = f"{base} Run /xp-kickoff."
    if smm_dir is not None and smm_dir_resolve.is_under_plugin_managed_root(smm_dir):
        template = _lock_advisory(migration_lock.lock_state(smm_dir))
        return f"{base} {template.format(tool=_tool_path())}"
    return base
