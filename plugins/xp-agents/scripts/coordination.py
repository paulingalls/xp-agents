#!/usr/bin/env python3
"""Coordination file management for multi-agent conflict detection.

Manages .coordination.json — a lightweight, lockable file that tracks
which agent is working on which files, enabling O(1) overlap checks.
"""

import contextlib
import json
import sys
import time
from contextlib import AbstractContextManager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
import session_scope
from _append_impl import write_json_atomic
from _try_flock import try_flock

_COORDINATION_MAX_AGE = 1800  # 30 minutes

# This file's acquire budget, deliberately shorter than the event log's 10s.
# `.coordination.json` is a best-effort advisory file read by gates that all
# degrade gracefully without it, and every write happens on the SYNCHRONOUS
# PostToolUse path — so blocking a hook for ten seconds on it is its own
# problem, worse than the stale entry a give-up leaves behind. `XP_LOCK_TIMEOUT_SECONDS`
# can SHORTEN this further — which is what lets a cross-process test narrow it —
# but no longer widen it, so tuning the event log's lock cannot inflate this cap.
_COORDINATION_LOCK_TIMEOUT_S = 2


def _coordination_lock(smm_dir: Path) -> AbstractContextManager[bool]:
    """Hold the coordination lock for the block. Yields whether it was taken.

    The shape is `_try_flock.try_flock`, shared with the in-place door mutex —
    which this used to merely resemble. This wrapper supplies the lock path, the
    2s budget, and the one thing the door does not want: a give-up is LOGGED
    rather than swallowed. This runs on a synchronous hook path where the
    alternative to a trace is a coordination entry that silently stopped being
    written; `tests/hooks/test_coordination_lock.py` carries the defect that
    caused.

    The cause is passed THROUGH, not flattened to "could not lock": which errno
    (`ENOLCK` on a network mount) or a timeout is the difference between a
    diagnosable give-up and an unexplained one. That is why the shared shape takes
    a callback instead of just returning a bool.
    """
    lock_path = smm_dir / marker_names.COORDINATION_LOCK

    def _log(exc: Exception) -> None:
        # Lazy, like `now_iso` below: this module loads on the write-path hooks,
        # and only a failing acquire needs the error-logging machinery.
        import _common

        _common.log_hook_error(
            f"coordination lock unavailable, entry left unchanged: {exc}",
            error_class=type(exc).__name__,
            lock_path=str(lock_path),
        )

    return try_flock(lock_path, timeout_s=_COORDINATION_LOCK_TIMEOUT_S, on_giveup=_log)


# How `has_active_teammates` reads the file unfiltered. `read_coordination` has
# no "no TTL" sentinel and must not grow one — its other callers depend on the
# filter — so the filter is disabled by asking for an age no real timestamp can
# exceed.
_NO_AGE_LIMIT = 10**9  # ~31 years

# How old another session's heartbeat may be before `has_active_teammates`
# reads that session as gone. A CALLER-side threshold, deliberately not the
# scan's own `STALE_AFTER_SECONDS`: that one is shared with the preload check
# and is loose (4h) because it must never refuse a user who stepped away
# between prompts. This question is the opposite — a Stop gate held on a
# teammate that no longer exists — and it has to answer inside the TTL it
# replaces, or the liveness leg makes a dead teammate look active for LONGER
# than the plain 30-minute TTL did.
#
# A killed session stops writing both files at once, so neither clock advances
# after death and the window alone decides when a dead teammate stops counting.
#
# The two clocks are NOT the same age, though, and the difference runs one way:
# the entry is written only from PostToolUse Write/Edit/MultiEdit, while the
# heartbeat is ALSO written from Bash, Skill/Agent and every user prompt. So a
# heartbeat is never older than its entry and is often much younger. Two
# consequences, both worth stating plainly rather than assuming away:
#
#   - Reading the heartbeat measures the age of the last PROOF OF LIFE, where
#     the TTL measured the age of the last file write. That is the better
#     clock, and it is why a teammate that has been running Bash for an hour
#     without writing a file is no longer forgotten.
#   - A window BELOW `_COORDINATION_MAX_AGE` therefore does not guarantee a
#     dead teammate is dropped sooner than the plain TTL would have dropped
#     it: one killed 5 minutes after its last Bash call but 25 after its last
#     write is held 10 minutes LONGER than the TTL alone would have. Bounded,
#     and in exchange for the bullet above — not the strict tightening the
#     ordering of the two numbers suggests.
#
# 15 minutes: the window has to exceed the longest gap between heartbeat writes
# on a WORKING session. A tool call alone is a comfortable fit — the longest
# here is a full-suite run, measured 5m35s alone and 9m49s with four sibling
# teammates on the same machine.
#
# Be honest about what it does NOT clear. Every heartbeat writer skips its own
# subagents, so nothing refreshes the marker for the DURATION of one: a session
# running a nested review that reads a large diff and runs the suite can pass
# 15 minutes with its hooks demonstrably alive. Read/Grep/Glob have no
# PostToolUse refresh either. So a live-but-quiet teammate read as dead is a
# state to expect, not a corner.
#
# What that costs differs by caller, and both now have a backstop. The sprint
# gate falls through to `worktree.has_live_teammates`, a registration check that
# still sees the teammate. The TDD gate had nothing and now answers a different
# question instead: `tdd_check._is_another_trees_agent` drops a worktree
# teammate's signals from the LEAD's read by AUTHOR, so the lead is never
# offered that failure to refuse on in the first place.
#
# Attribution rather than a second liveness check, because the gap it closes is
# not this window at all. A teammate that edits only through Bash never gets a
# coordination entry (`post_tool_use` is the sole writer and is registered on
# Write|Edit), and `has_active_teammates` iterates ENTRIES — so no entry means
# the heartbeat below is never consulted for that agent. That failure sits
# upstream of this number and is permanent, not a window; an earlier version of
# this comment surveyed the TTL-shaped instance and read as if it had surveyed
# the whole gap.
#
# The number itself is unaffected by that correction, and stands: raising it is
# still not the fix if the TTL-shaped case bites, because it buys a false block
# back as a longer false release. A refresh source that survives a subagent run
# is, and remains open.
_HEARTBEAT_TRUST_SECONDS = 15 * 60


def update_coordination(smm_dir: Path, agent_id: str, working_on: list[str]) -> None:
    """Atomically update this agent's entry in .coordination.json."""
    coord_path = smm_dir / marker_names.COORDINATION_JSON

    with _coordination_lock(smm_dir) as held:
        if not held:
            return
        # Read existing data
        data: dict = {}
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            data = json.loads(coord_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        # Update agent entry
        from _common import now_iso

        # `session_id` records WHICH SESSION wrote this, so a reader can ask
        # whether that session's hook runtime is still beating instead of
        # trusting the timestamp. `session_scope` directly, never via
        # `hook_liveness`: its `resolve_session_id` is a one-line delegate to
        # this same chain, and importing it would pull the hook runtime onto
        # the write path every file write goes through.
        #
        # None reaches the file as None, and that is the point. No candidate
        # set (an unfamiliar host) and candidates that DISAGREE (an inherited
        # id, which `resolve_session_id` refuses rather than guesses between)
        # both mean "cannot tell", which the reader turns back into today's
        # TTL rather than into a verdict.
        data[agent_id] = {
            "working_on": working_on,
            "updated": now_iso(),
            "session_id": session_scope.resolve_session_id(),
        }

        write_json_atomic(coord_path, data)


def read_coordination(
    smm_dir: Path, max_age_seconds: int = _COORDINATION_MAX_AGE
) -> dict:
    """Read .coordination.json, filtering out stale entries."""
    coord_path = smm_dir / marker_names.COORDINATION_JSON
    try:
        data = json.loads(coord_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result: dict = {}
    for aid, entry in data.items():
        if not isinstance(entry, dict):
            continue
        updated_str = entry.get("updated", "")
        try:
            updated = datetime.fromisoformat(updated_str)
            if (now - updated).total_seconds() <= max_age_seconds:
                result[aid] = entry
        except (ValueError, TypeError):
            continue
    return result


def _session_is_live(smm_dir: Path, session_id: object) -> bool | None:
    """Is the session that wrote an entry still beating? None = cannot tell.

    Reuses the heartbeat every hook already refreshes — there is no second
    liveness implementation here, and must not be. Any reader added for this
    question has to take a SESSION ID: one that does not can only answer about
    the process it runs in, which is never the process being asked about. Only
    the freshness threshold is
    ours: see `_HEARTBEAT_TRUST_SECONDS` for why this caller cannot use the
    scan's own, and what a teammate quieter than it gets.

    Imported lazily. This module is loaded by the write-path hooks, which do
    not ask the question, and only the Stop gates pay for the extra modules.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        return None

    import hook_heartbeat_scan
    import hook_liveness
    import markers

    path = markers.marker_path(smm_dir, hook_liveness.heartbeat_marker(session_id))
    age = hook_heartbeat_scan.sibling_age(smm_dir, path, time.time())
    # `sibling_age` returns None for every heartbeat it cannot age — absent,
    # symlinked, corrupt, unparseable timestamp — and all four stay
    # UNDETERMINED here rather than becoming a death.
    #
    # Absence is the tempting one to read as death, and it must not be. The
    # heartbeat is keyed on the id the host handed the hook while this entry is
    # keyed on the id the environment exposes; where those two sources differ,
    # a live session's entry addresses a marker nothing ever writes. A writer
    # whose heartbeat write failed (symlinked marker, full disk — it swallows
    # and logs) leaves the same hole. Reading either as "dead" would hold a
    # lead at Stop over a teammate that is working.
    return (
        None
        if age is None
        else hook_heartbeat_scan.within_window(age, _HEARTBEAT_TRUST_SECONDS)
    )


def has_active_teammates(smm_dir: Path, agent_id: str) -> bool:
    """Return True if another agent is genuinely active in coordination.

    Time is not liveness, and a timestamp-only answer errs in BOTH directions:
    it releases a Stop gate on a dead agent whose entry is merely recent, and
    it forgets a live-but-quiet teammate whose entry aged out — after which
    the lead reads that teammate's unresolved failing-test concern as its own
    and falsely blocks. So the entries are read unfiltered and the session
    heartbeat decides.

    Undetermined liveness — an entry written before the session id was
    recorded, a host that exposes none, a heartbeat that cannot be read —
    falls back to the TTL, which is exactly today's behaviour.

    An entry this session wrote is one of those undetermined shapes: our own
    heartbeat cannot vouch for another agent id, so the entry's own age decides.
    One file write by a subagent of ours therefore releases this gate for the
    length of the TTL, and closing that needs provenance the entry does not
    carry — not a different threshold. Measured in
    test_own_session_entry_release.py rather than only asserted here.

    Bounded further than it looks, and worth stating: `post_tool_use` refreshes
    the entry only on a tool call that names a FILE, so a subagent of ours that
    reads, greps or shells for longer than the TTL ages out and stops counting.
    A teammate has the heartbeat as a second leg; an own-session entry does not,
    because the whole point is that our heartbeat cannot vouch for it.

    The liveness leg stops here. `read_coordination` keeps its filter for
    every other caller: making the write-conflict detector liveness-aware
    would pin a live-but-quiet teammate's last-written file as a rival
    indefinitely, since the TTL is the only thing that frees it.
    """
    own_session = session_scope.resolve_session_id()
    within_ttl = read_coordination(smm_dir)
    for aid, entry in read_coordination(smm_dir, _NO_AGE_LIMIT).items():
        if aid == agent_id:
            continue
        written_by = entry.get("session_id")
        # Agent id and session are different keys, and one session holds
        # several agent ids: a non-xp subagent writes its own entry under its
        # own id inside OUR session. Our heartbeat must not VOUCH for that
        # entry — it says nothing about whether that agent id still exists — so
        # it reads as UNDETERMINED and the entry's own age decides.
        #
        # NOT skipped outright, which sprint-005 briefly shipped and reverted: a
        # BACKGROUNDED non-xp subagent is not skipped by `post_tool_use`'s
        # is_xp_agent guard and really does edit files while the lead sits at
        # Stop, so discarding its entry nudged the lead to close a sprint
        # mid-write and held it on a red suite that agent may have caused. The
        # gates ask whether someone else may be writing, not whether the writer
        # is a teammate.
        live = (
            None
            if own_session is not None and written_by == own_session
            else _session_is_live(smm_dir, written_by)
        )
        if live is True or (live is None and aid in within_ttl):
            return True
    return False


def clear_coordination_agent(smm_dir: Path, agent_id: str) -> None:
    """Remove an agent's entry from .coordination.json."""
    coord_path = smm_dir / marker_names.COORDINATION_JSON

    with _coordination_lock(smm_dir) as held:
        if not held:
            return
        data: dict = {}
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            data = json.loads(coord_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        if agent_id in data:
            del data[agent_id]
            write_json_atomic(coord_path, data)
