#!/usr/bin/env python3
"""Scanning the per-session heartbeat files: the window, the ages, the reap.

One heartbeat PER SESSION, not one per SMM. The SMM is deliberately shared:
spawners export SMM_DIR verbatim to their teammates, and two windows on one
repo hash the same git-common-dir to the same project id. A single marker
keyed on one session id is therefore last-writer-wins — the moment a teammate
starts, the lead reads someone else's id and is told the plugin is probably
not loaded. The primary signal would manufacture the false alarm it exists
to prevent, in the mode this project is built around.

Per-session FILES rather than a set of ids inside one file: concurrent
sessions would otherwise read-modify-write the same marker with no lock
between them, and a lost update reads exactly like a dead runtime. That
choice is what makes a scan necessary, and this module is that scan —
extracted from `hook_liveness` so a reader asking about ANOTHER session's
runtime (`coordination.has_active_teammates`) can age one heartbeat without
importing the verdict machinery, which only ever answers about the process
it runs in.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import marker_names
import markers
import session_markers

# How long a heartbeat stays trustworthy. Four hours is deliberately loose:
# it must never refuse a user who stepped away between prompts, because a
# check that false-refuses is a check people switch off.
#
# Be honest about what that costs. With session-id matching carrying the
# precision, this leg's only remaining job is catching a runtime that dies
# MID-session, and at four hours it will not catch that quickly. A
# higher-frequency refresh source now exists — every Bash, every
# Write/Edit/MultiEdit and every Skill call refreshes this — but it does not
# yet cover the tool surface: Read/Grep/Glob have no PostToolUse handler, so a
# long read-only stretch still ages out while hooks are demonstrably running.
# Tightening therefore waits on two things, not one: closing that gap, and a
# session sitting IDLE between prompts.
STALE_AFTER_SECONDS = 4 * 60 * 60

# How far in the FUTURE a heartbeat's timestamp may sit and still be believed.
#
# The window is bounded at both ends, for the same reason the housekeeping
# in-flight record's is: `age >= STALE_AFTER_SECONDS` alone reads a negative age
# as fresh FOREVER, so one wall-clock step backwards (NTP correction, VM
# snapshot restore, a resume with a bad RTC) or a millisecond timestamp where
# seconds were meant would report "live" for the rest of the session even after
# the runtime died — the silent unenforcement the heartbeat exists to detect.
#
# It is a tolerance rather than a hard `0 <= age` because refusing a working
# session is the failure that gets a check switched off, and a heartbeat is
# rewritten by the next Bash, Write/Edit or Skill call: if the runtime is alive
# a future timestamp self-heals within one tool call, so the refusal only
# persists when the runtime is genuinely gone. A minute absorbs ordinary slew
# without absorbing either failure above.
FUTURE_SKEW_GRACE_SECONDS = 60

# The suffixed files one glob addresses. It deliberately does NOT match the
# unsuffixed shared marker a no-id host writes: that file is the only heartbeat
# such a host has, and reaping it would delete the signal rather than expire it.
SESSION_GLOB = f"{marker_names.HOOK_HEARTBEAT}-*"


def within_window(age: float | None, stale_after: float = STALE_AFTER_SECONDS) -> bool:
    """True only for an age that is usable AND inside the window at BOTH ends.

    One home for the bounds, so the scans that ask "is this heartbeat still
    good" cannot drift apart. None (unageable) and a timestamp further ahead
    than the skew grace are both "not evidence of freshness" — see
    FUTURE_SKEW_GRACE_SECONDS for why the far end is bounded at all.

    `stale_after` is the far end only, and it is a parameter because "still
    good" is not one question: the preload check tolerates a user who stepped
    away between prompts, while a Stop gate deciding whether to release on a
    teammate cannot. A caller that needs a tighter answer passes its own value
    rather than growing a second implementation — the near end, the None
    handling, and the comparison itself stay here.
    """
    return age is not None and -FUTURE_SKEW_GRACE_SECONDS <= age < stale_after


def sibling_age(smm_dir: Path, path: Path, now: float) -> float | None:
    """Age of another session's heartbeat, or None if it is unusable.

    Rebuilds a `MarkerDef` from the filename so the read goes back through
    `markers.marker_read` — symlink rejection and corrupt-JSON handling stay
    in the one place that owns them.
    """
    data = markers.marker_read(smm_dir, markers.MarkerDef(path.name, "json"))
    if not isinstance(data, dict):
        return None
    return session_markers.marker_age_seconds(now, data.get("written_at"))


def reap_stale_siblings(smm_dir: Path, keep: Path, now: float) -> None:
    """Delete other sessions' expired heartbeats. Best-effort, never raises.

    Per-session files would otherwise accumulate one per session forever.
    Reaping on write keeps it self-contained — no cleanup hook to wire, and
    the work is bounded by the number of live-ish sessions.

    Only expired or unreadable siblings go. A fresh one belongs to a session
    that may still be running, and deleting it would make that session
    believe its own hooks had stopped.
    """
    for path in smm_dir.glob(SESSION_GLOB):
        if path == keep or path.is_symlink():
            continue
        try:
            if within_window(sibling_age(smm_dir, path, now)):
                continue
            path.unlink()
        except OSError:
            continue


def freshest_sibling(smm_dir: Path, now: float) -> float | None:
    """Age of the youngest per-session heartbeat still inside the threshold.

    None means no other session's hooks have run recently. Two callers in
    `hook_liveness` need "is the runtime alive anywhere" — the absent-marker
    path and the stale path — and they must reach the same answer without
    sharing a verdict, because absence and staleness are different diagnoses
    even when the scan result is identical.

    What this no longer feeds is a LIVE verdict. A neighbour's heartbeat is
    evidence about that neighbour; both callers use this only to say so in
    their refusal.
    """
    freshest: float | None = None
    for path in smm_dir.glob(SESSION_GLOB):
        age = sibling_age(smm_dir, path, now)
        # `within_window` already rejects None; the explicit leg is what lets a
        # static reader narrow `age` to a float for the `min` below.
        if age is None or not within_window(age):
            continue
        freshest = age if freshest is None else min(freshest, age)
    return freshest
