#!/usr/bin/env python3
"""Coordination file management for multi-agent conflict detection.

Manages .coordination.json — a lightweight, lockable file that tracks
which agent is working on which files, enabling O(1) overlap checks.
"""

import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import marker_names
import session_scope
from _append_impl import write_json_atomic

_COORDINATION_MAX_AGE = 1800  # 30 minutes

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
# What that costs differs by caller, and only one of them has a backstop. The
# sprint gate falls through to `worktree.has_live_teammates`, a registration
# check that still sees the teammate. The TDD gate does not: it reaches this
# question only on the LEAD's unscoped read, so the red suite it then refuses
# to stop on may be the teammate's rather than its own, and the lead re-runs
# its own suite to clear it. Neither error is silent and both self-heal within
# a tool call, which is why the number is left where the story set it. Raising
# it is not the fix if this bites, because it buys the false block back as a
# longer false release. A refresh source that survives a subagent run is.
_HEARTBEAT_TRUST_SECONDS = 15 * 60


def update_coordination(smm_dir: Path, agent_id: str, working_on: list[str]) -> None:
    """Atomically update this agent's entry in .coordination.json."""
    import fcntl
    import signal

    lock_path = smm_dir / marker_names.COORDINATION_LOCK
    coord_path = smm_dir / marker_names.COORDINATION_JSON

    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return

    try:
        old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(2)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (OSError, SystemExit):
            return
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

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
    finally:
        os.close(lock_fd)


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
    liveness implementation here, and must not be. `check_liveness` is the
    wrong reader for this question: it takes no session id, so it can only
    ever answer about the process it runs in. Only the freshness threshold is
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
        # own id inside OUR session. Our heartbeat says nothing about whether
        # THAT agent still exists, so an entry we wrote ourselves is
        # undetermined, not live — otherwise a subagent that never reached its
        # completion handler would hold the gate released for the whole
        # session, where the TTL dropped it at 30 minutes. No real teammate is
        # caught by this: `spawn_teammate` strips every session-id candidate
        # from the child's environment, so a teammate resolves its own id or
        # records None.
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
    import fcntl
    import signal

    coord_path = smm_dir / marker_names.COORDINATION_JSON
    lock_path = smm_dir / marker_names.COORDINATION_LOCK

    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return

    try:
        old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(2)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (OSError, SystemExit):
            return
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        data: dict = {}
        with contextlib.suppress(FileNotFoundError, json.JSONDecodeError):
            data = json.loads(coord_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}

        if agent_id in data:
            del data[agent_id]
            write_json_atomic(coord_path, data)
    finally:
        os.close(lock_fd)
