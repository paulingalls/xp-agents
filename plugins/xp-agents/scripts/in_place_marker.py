#!/usr/bin/env python3
"""In-place teammate marker: lifetime-scoped presence + pid-liveness.

A solo/in-place teammate runs in the MAIN checkout, so — unlike a worktree
teammate — its cwd carries no path marker to identify it by. This marker is
that missing signal. It is written by `spawn_teammate --in-place` and read by
two consumers that pull in OPPOSITE directions, which is the whole design
problem here:

  - `in_place_marker_exists` (existence-only) — identity, pre_tool_skill and
    commit_handling pair it with a non-None XP_TEAMMATE_NAME to decide whether
    a process IS a teammate. A LIVE teammate must never lose its marker, or it
    is demoted to the lead: skill gating drops and its commits are misattributed.

  - `has_live_in_place_teammate` (pid-liveness) — the accept gate has no name to
    pair with, so it pays for a liveness probe. A DEAD teammate must never
    suppress the gate, or `/xp-accept` certifies a half-written tree.

Reconciling the two is what the pid list buys: the marker records every process
whose life means the episode is still in flight, reads live while ANY survives,
and is reaped only once ALL are PROVEN dead — the sole condition under which
neither consumer can be harmed.

Split from worktree.py (which crossed the 500-line ceiling); re-exported there,
so `worktree.<name>` remains the import surface for existing call sites.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import marker_names


def in_place_marker_path(smm_dir: Path, name: str) -> Path:
    """Return the path to an in-place teammate's lifetime-scoped active marker."""
    return smm_dir / marker_names.IN_PLACE_ACTIVE.format(name=name)


def write_in_place_marker(
    smm_dir: Path, name: str, child_pid: int | None = None
) -> None:
    """Atomically write the in-place active marker with symlink rejection.

    Written by spawn_teammate --in-place for the episode's lifetime only;
    commit_handling requires it before trusting the leaky XP_TEAMMATE_NAME env.

    Content is a whitespace-separated list of the pids of EVERY process whose
    life means the in-place episode is still in flight (not the teammate name) —
    so has_live_in_place_teammate can probe liveness without knowing the name.

    Called TWICE by the same owner, never by a second writer:
      1. before the spawn (child_pid=None) — only the supervisor exists yet, and
         the marker must already be on disk or the child's first hook loses the
         identity race;
      2. again once Popen returns (child_pid=<claude pid>) — the child is the
         actual teammate, and it can OUTLIVE this supervisor (see
         _marker_pid_alive), so its pid is the one that must keep the marker
         alive after a SIGKILL up here.
    Both writes are atomic, so a concurrent reader sees one list or the other —
    each true when written — never a torn file.
    """
    from _append_impl import write_text_atomic

    path = in_place_marker_path(smm_dir, name)
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    pids = [os.getpid()] if child_pid is None else [os.getpid(), child_pid]
    write_text_atomic(path, " ".join(str(p) for p in pids))


def remove_in_place_marker(smm_dir: Path, name: str) -> None:
    """Remove the in-place active marker (idempotent)."""
    in_place_marker_path(smm_dir, name).unlink(missing_ok=True)


def in_place_marker_exists(smm_dir: Path, name: str) -> bool:
    """True when an in-place teammate marker exists for `name`.

    Deliberately existence-only, NOT pid-liveness like has_live_in_place_teammate
    below: every caller pairs this with a non-None XP_TEAMMATE_NAME, and that
    pairing is what makes a leaked marker inert for them. Adding a liveness probe
    here to "match" would flip the fail direction for those callers — a probe
    misfire would demote a LIVE teammate to the lead and lose its commit
    attribution. The gate's name-free probe has no name to pair with, which is
    why it (and only it) pays for liveness.
    """
    return in_place_marker_path(smm_dir, name).is_file()


def _probe_pid(pid: int) -> bool | None:
    """True = alive, False = PROVEN dead, None = cannot adjudicate.

    POSIX-only: os.kill(pid, 0) is a liveness probe here, but on Windows it
    would terminate the target. The plugin is already POSIX (flock, bash
    preloads), so this is a note, not a branch.

    "Proven dead" is a strictly narrower claim than "not alive", and only the
    former may authorize a reap — hence three states, not two.
    """
    if pid <= 0:
        # os.kill(0, 0) signals our OWN process group and SUCCEEDS; negative
        # pids are process-GROUP targets. Neither is a pid we wrote, so this is
        # corruption: not alive, but not proof of death either.
        return None
    try:
        os.kill(pid, 0)
    except OverflowError:
        # int() is arbitrary-precision but os.kill needs a C int. OverflowError
        # is an ArithmeticError, so it escapes the OSError clauses below and
        # would CRASH the Stop hook -- a crash means the gate never fires at all.
        return None
    except ProcessLookupError:
        return False  # proven dead
    except OSError:
        # PermissionError: the pid EXISTS but is owned by another uid, so it is
        # not our teammate (which runs as us) — unadjudicable, and certainly not
        # proof of death.
        return None
    return True


def _marker_pid_alive(path: Path) -> bool:
    """True when ANY process recorded in the marker is still alive.

    The marker lists the supervising spawn_teammate AND the `claude` child it
    launched. Both must be probed, because the child can OUTLIVE the supervisor:
    the supervisor is only a tee (plain Popen, no start_new_session), so a
    SIGTERM/SIGKILL delivered to its pid does NOT propagate to the child. The
    child is reparented to init and keeps running — indefinitely, if it is mid
    silent stretch (a long model call; the watchdog tolerates 900s of these).
    Only a chatty child dies promptly, on BrokenPipe at its next stdout write.
    Probing the supervisor alone would therefore read DEAD while a live teammate
    is still writing the tree, firing the accept gate mid-flight AND reaping the
    live teammate's marker out from under it (demoting it to the lead).

    Leaks are routine, not exotic: Python installs no SIGTERM handler, so
    spawn_teammate's marker-removing `finally` does NOT run when a backgrounded
    spawn is cancelled (the usual kill path) — only on a clean exit or SIGINT.
    An unreadable/unparseable marker therefore fails OPEN (reads dead -> the gate
    fires): a suppressed accept gate certifies a half-written tree silently,
    whereas a spurious one merely nags.

    Reaping is the opposite bet and needs the opposite bar. A marker is unlinked
    only when EVERY recorded pid is PROVEN dead — the one condition under which
    no consumer can be harmed. That keeps leaks from accumulating until a
    recycled pid reads live again and re-suppresses the gate, without ever
    deleting the marker of a teammate that is merely un-adjudicable.
    """
    try:
        tokens = path.read_text().split()
    except OSError:
        # Vanished mid-scan (spawn_teammate's finally), or unreadable.
        return False
    try:
        pids = [int(t) for t in tokens]
    except ValueError:
        # A legacy name-content marker, which may belong to a teammate still
        # running the older code — unadjudicable, so it is NOT reaped.
        return False
    if not pids:
        return False  # empty marker: not alive, but not proof of death
    verdicts = [_probe_pid(p) for p in pids]
    if any(v is True for v in verdicts):
        return True
    if all(v is False for v in verdicts):
        path.unlink(missing_ok=True)
    return False


def has_live_in_place_teammate(smm_dir: Path) -> bool:
    """True when a LIVE in-place teammate marker exists, whatever its name.

    Every marker is probed, and the verdicts are collected BEFORE they are
    aggregated: the reap is a side effect of the probe, so short-circuiting on
    the first live marker (`any(gen)`) would leak every dead marker behind it,
    and which ones got reaped would depend on the order the filesystem happened
    to yield. `sorted` pins that order so the scan is reproducible.
    """
    pattern = marker_names.IN_PLACE_ACTIVE.format(name="*")
    verdicts = [_marker_pid_alive(p) for p in sorted(smm_dir.glob(pattern))]
    return any(verdicts)


def in_place_teammate_from_env(smm_dir: Path, env_name: str | None) -> bool:
    """True when env_name names a live in-place teammate (marker present).

    Wraps the env-name-not-None + in_place_marker_exists check the three
    call sites (identity, pre_tool_skill, commit_handling) rolled by hand.
    Caller-side id-shape validation (is_teammate_agent_id) and smm_dir
    resolution stay at the call sites, which differ.
    """
    return env_name is not None and in_place_marker_exists(smm_dir, env_name)
