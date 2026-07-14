#!/usr/bin/env python3
"""In-place teammate marker: the NAME a teammate holds, and the LOCK that says
whether it is still alive.

A solo/in-place teammate runs in the MAIN checkout, so — unlike a worktree
teammate — its cwd carries no path marker to identify it by. This marker is that
missing signal. Two consumers read it, and they pull in OPPOSITE directions,
which is the whole design problem:

  - `in_place_marker_exists` (existence-only) — identity, pre_tool_skill and
    commit_handling pair it with a non-None XP_TEAMMATE_NAME to decide whether a
    process IS a teammate. A LIVE teammate must never lose its marker, or it is
    demoted to the lead: skill gating drops and its commits are misattributed.

  - `has_live_in_place_teammate` (liveness) — the accept gate has no name to pair
    with, so it pays for a liveness verdict. A DEAD teammate must never suppress
    the gate, or `/xp-accept` certifies a half-written tree.

LIVENESS IS A LOCK:

    alive(name) := the holder lock is HELD  OR  the recorded child pid is alive

The holder lock (in_place_locks) is held by the supervisor for the whole episode,
and the KERNEL releases it when that supervisor dies, however it dies. Pids
cannot do that job: the supervisor's marker-removing `finally` does not run under
SIGKILL — the ROUTINE cancel path for a backgrounded spawn — so leaked markers
are normal, and a leaked marker's pid can be RECYCLED to an unrelated live
process, which then reads LIVE forever and wedges that name against every
respawn. The recorded supervisor pid is therefore ADVISORY now; the lock decides.

The OR-leg is not a hedge. spawn_teammate is only a TEE around the real teammate:
a SIGKILL to it does NOT propagate to the `claude` child, which is reparented to
init and keeps writing the tree. A lock-ONLY verdict would read DEAD there —
reaping a LIVE teammate's marker, firing the accept gate on a half-written tree,
and letting a respawn admit a SECOND `claude` into the same checkout.

THE MARKER IS THE INDEX; THE LOCK IS THE VERDICT. Glob markers FIRST, and only
then consult a lock. No marker ⇒ no lock is opened, created, or probed: a
nonexistent SMM dir answers False (an O_CREAT there would raise), the common Stop
pays ZERO lock cost, and stray lock files stay bounded.

WHAT THIS DOES NOT CLOSE, stated plainly:
  - rm'ing a LIVE teammate's marker still BLINDS the Stop gate (no marker, no
    lock consulted). The name stays refused to a claimant, but the gate goes
    quiet. Not a regression — the old glob did the same — but not closed either.
  - a RECYCLED CHILD pid reads LIVE and refuses the name. Rm-recoverable, and the
    price of not regressing the live-orphan case above.
  - rm'ing a holder LOCK does not, on its own, free a live name — but only
    because of _legacy_verdict. With the lock file gone the name falls back to the
    OLD pid adjudication, which still refuses while the marker's pids read alive.
    So the lock and the marker COVER EACH OTHER: rm both (or rm the lock under an
    unreadable marker) and the name goes free under a live teammate — two
    `claude`s in one checkout. Two consequences worth stating: nothing in the tree
    globs `*.lock` and nothing should start (a sweep would take the lock leg
    away), and _legacy_verdict is NOT merely a migration shim to delete once the
    old markers age out — deleting it re-opens this hole.

Split from worktree.py (which crossed the 500-line ceiling); re-exported there,
so `worktree.<name>` remains the import surface for existing call sites.
"""

import contextlib
import os
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import in_place_locks
import marker_names
from _append_impl import write_text_atomic

# The three verdicts. "PROVEN dead" is a strictly narrower claim than "not
# alive", and only the former may ever authorize a reap — hence three, not two.
_LIVE = "live"
_DEAD = "dead"
_UNPROVEN = "unproven"


class _Verdict(NamedTuple):
    """A liveness verdict, plus the holder lock we took while reaching it.

    `hold` is an fd ONLY on a _DEAD verdict reached through a holder lock — we
    took that lock to PROVE the holder was gone, and we still have it. Whoever
    asked must either keep it (a claim: it is now the episode's hold) or release
    it (a reap: it was transient, which is what the door mutex hides).
    """

    state: str
    hold: int | None


def in_place_marker_path(smm_dir: Path, name: str) -> Path:
    """Return the path to an in-place teammate's lifetime-scoped active marker."""
    return smm_dir / marker_names.IN_PLACE_ACTIVE.format(name=name)


class InPlaceNameHeld(Exception):
    """A live (or unadjudicable) in-place teammate already holds this name.

    Refusing is the point. Two live teammates under one name is the state the
    marker exists to prevent: two `claude` processes writing one checkout, and
    whichever tears down first deletes the other's marker. Failing the spawn
    LOUDLY is recoverable (kill the holder, or rm a corrupt marker); silently
    demoting a running teammate to the lead is not.
    """


def claim_in_place_marker(smm_dir: Path, name: str) -> None:
    """Take the name for this supervisor, or raise InPlaceNameHeld.

    The door that makes a name EXCLUSIVE, and the only one that creates a lock.
    It adjudicates exactly as the reap does — a claim that blindly unlinked
    whatever marker it found would clobber a LEGACY one belonging to a live
    old-code teammate:

      - LIVE      -> refuse. (Two live teammates under one name is the state we
                    never want.)
      - UNPROVEN  -> refuse, marker byte-intact. Not proof of death, so we may
                    not delete it; recoverable by inspecting and rm'ing it.
      - DEAD      -> take the lock, unlink the stale marker, publish ours, and
                    KEEP the hold for the rest of the episode.

    The lock is created BEFORE the marker is published, always — which is what
    makes "marker present, lock absent" unambiguously a pre-lock artifact, and
    lets the legacy fallback exist at all.

    On a door-mutex failure it REFUSES. It must never fall through to publish:
    two claimants both publishing is two `claude` processes in one checkout.

    Content is the pid list — us now, plus the child once Popen returns
    (rewrite_own_in_place_marker). The supervisor pid is advisory; the child's is
    the OR-leg.
    """
    marker = in_place_marker_path(smm_dir, name)
    holder = in_place_locks.holder_lock_path(smm_dir, name)
    with in_place_locks.door_mutex(smm_dir) as mutex_held:
        if not mutex_held:
            raise InPlaceNameHeld(
                f"cannot claim {name!r}: the in-place door mutex is unavailable, "
                "so the name cannot be adjudicated. Refusing rather than risking "
                "a second teammate in the same checkout."
            )
        verdict = _adjudicate(smm_dir, name)
        if verdict.state != _DEAD:
            raise InPlaceNameHeld(_refusal(name, marker, verdict.state))

        fd = verdict.hold
        if fd is None:  # a free name, or a legacy marker: no lock file yet
            fd = in_place_locks.create_holder_lock(holder)
        if fd is None:
            raise InPlaceNameHeld(
                f"cannot claim {name!r}: the holder lock {holder} could not be "
                "taken. Inspect it and remove it to respawn."
            )
        in_place_locks.keep_holder_lock(holder, fd)
        try:
            marker.unlink(missing_ok=True)  # a stale marker we PROVED dead
            write_text_atomic(marker, str(os.getpid()))
        except BaseException:
            # A held name with no marker is invisible to the reap (the marker is
            # the index) and would block every respawn forever. Give it back.
            in_place_locks.release_own_holder_lock(smm_dir, name)
            raise


def _refusal(name: str, marker: Path, state: str) -> str:
    match state:
        case "live":
            return (
                f"a live in-place teammate already holds {name!r} ({marker}). "
                "Kill its supervisor AND its `claude` child, then respawn: the "
                "claim reaps the leaked marker itself once both are PROVEN dead. "
                "Only if it still refuses with nothing running is the holder lock "
                "unreadable rather than held — rm the lock then, never while a "
                "teammate is alive under the name (an rm'd lock is a lock nobody "
                "holds)."
            )
        case _:
            return (
                f"cannot claim {name!r}: {marker} is held by a marker that is "
                "neither live nor provably dead (a legacy, corrupt, or "
                "foreign-owned marker). Inspect it and remove it to respawn."
            )


def rewrite_own_in_place_marker(smm_dir: Path, name: str, child_pid: int) -> None:
    """Fold the child's pid into the marker. Takes NO lock — we hold one already.

    The child is the actual teammate and can OUTLIVE this supervisor (we are only
    a tee; a SIGKILL up here does not propagate to it), so its pid is the OR-leg
    that keeps the marker alive after our lock is released. Recording only ours
    would let the reap collect a LIVE teammate's marker.

    Gated on HOLDING the name, not on the marker's content. The old content check
    ("the first pid is mine") was forgeable by a writer against itself — write the
    marker, then read your own pid back as proof of ownership — which is precisely
    how a supervisor came to overwrite, and then delete, a live teammate's marker.
    A lock cannot be forged. If we do not hold the name, this is a no-op, and the
    safe one: our child's pid simply goes unrecorded, so the episode reads dead
    once WE exit — failing OPEN (the accept gate fires), the direction the whole
    module leans.

    Needs no door mutex: the mutex exists to hide TRANSIENT holder-lock holds from
    a claimant, and this takes none. A concurrent reap cannot be harmed either —
    it finds our lock HELD, reads LIVE, and unlinks nothing.
    """
    if not in_place_locks.holds_name(smm_dir, name):
        return
    write_text_atomic(in_place_marker_path(smm_dir, name), f"{os.getpid()} {child_pid}")


def remove_own_in_place_marker(smm_dir: Path, name: str) -> None:
    """Give the name back: unlink the marker, then release the hold. Idempotent.

    Ownership is the HOLD — if we do not hold the name, there is nothing of ours
    here and we touch nothing. That single check replaces the whole content +
    inode-identity apparatus this door used to need, because the door mutex now
    makes the unlink and any concurrent publish mutually exclusive: nobody can
    slip a fresh marker onto the path between our adjudication and our unlink.

    Marker FIRST, lock SECOND. Between the two, the name is held with no marker —
    invisible to the reap (the marker is the index), which is harmless for the
    microseconds we hold the mutex. The reverse order would expose the opposite:
    a marker with a free lock, which a racing reap would (correctly, by its own
    rules) collect.

    On a door-mutex failure: release the lock, SKIP the unlink. The kernel drops
    the lock when we exit anyway, so the name is freed either way; the leaked
    marker is inert — the next claim adjudicates it, the next Stop reaps it.

    NEVER unlinks the lock file itself. See in_place_locks.
    """
    if not in_place_locks.holds_name(smm_dir, name):
        return
    with in_place_locks.door_mutex(smm_dir) as mutex_held:
        if mutex_held:
            with contextlib.suppress(OSError):
                in_place_marker_path(smm_dir, name).unlink(missing_ok=True)
        in_place_locks.release_own_holder_lock(smm_dir, name)


def in_place_marker_exists(smm_dir: Path, name: str) -> bool:
    """True when an in-place teammate marker exists for `name`.

    Deliberately existence-only, NOT liveness like has_live_in_place_teammate
    below: every caller pairs this with a non-None XP_TEAMMATE_NAME, and that
    pairing is what makes a leaked marker inert for them. Adding a liveness probe
    here to "match" would flip the fail direction for those callers — a probe
    misfire would demote a LIVE teammate to the lead and lose its commit
    attribution. The gate's name-free verdict has no name to pair with, which is
    why it (and only it) pays for liveness.
    """
    return in_place_marker_path(smm_dir, name).is_file()


def has_live_in_place_teammate(smm_dir: Path) -> bool:
    """True when a LIVE in-place teammate marker exists, whatever its name.

    Reaps every marker it PROVES dead — this call is not side-effect-free — which
    is what stops leaks accumulating. The verdicts are collected BEFORE they are
    aggregated: the reap is a side effect of the probe, so short-circuiting on the
    first live marker (`any(gen)`) would leak every dead marker behind it, and
    which ones got reaped would depend on the order the filesystem yielded them.
    `sorted` pins that order so the scan is reproducible.

    On a door-mutex failure it still ANSWERS, and skips only the UNLINK. Both
    halves of that are load-bearing. Raising would CRASH the Stop hook, and a gate
    that crashes never fires at all. Blanket-answering False would say "no live
    teammate" about a teammate that is very much alive — firing the accept gate on
    a half-written tree, which is the exact defect this marker exists to prevent.
    """
    names = _marker_names(smm_dir)
    if not names:
        return False  # the fast path: no marker ⇒ no lock is touched at all
    with in_place_locks.door_mutex(smm_dir) as may_unlink:
        return any([_reap(smm_dir, n, may_unlink=may_unlink) for n in names])


def _marker_names(smm_dir: Path) -> list[str]:
    """The names with a marker on disk, sorted. Glob yields nothing (rather than
    raising) for a missing dir, which is what makes the fast path above safe."""
    prefix = marker_names.IN_PLACE_ACTIVE.format(name="")
    pattern = marker_names.IN_PLACE_ACTIVE.format(name="*")
    return sorted(p.name[len(prefix) :] for p in smm_dir.glob(pattern))


def _reap(smm_dir: Path, name: str, *, may_unlink: bool) -> bool:
    """Adjudicate one name; unlink it if PROVEN dead. Returns "is it live".

    The unlink needs the door mutex, the ANSWER does not — so `may_unlink` gates
    only the delete. A skipped reap leaks a marker, and a leaked marker is inert:
    it reads dead, suppresses nothing, and the next Stop collects it.

    Answering without the mutex is not free: the adjudication itself takes a
    transient holder lock, and without the mutex to hide it a concurrent claimant
    can read that hold as LIVE and refuse a name it could have taken. A loud,
    recoverable refusal is the correct thing to trade for never certifying a
    half-written tree.
    """
    verdict = _adjudicate(smm_dir, name)
    if verdict.state == _DEAD and may_unlink:
        with contextlib.suppress(OSError):
            in_place_marker_path(smm_dir, name).unlink(missing_ok=True)
    if verdict.hold is not None:
        # A transient hold, taken only to prove the holder dead. The door mutex is
        # what kept it invisible to a concurrent claimant.
        in_place_locks.release_holder_lock(verdict.hold)
    return verdict.state == _LIVE


def _adjudicate(smm_dir: Path, name: str) -> _Verdict:
    """The one place liveness is decided. Every door goes through it.

    Existence of the lock FILE is tested before it is opened, and that is
    load-bearing: an unconditional O_CREAT would create the missing lock file for
    a LEGACY marker, acquire it (nobody holds it), read DEAD, and reap a marker
    that may belong to a live teammate running the old code.
    """
    holder = in_place_locks.holder_lock_path(smm_dir, name)
    marker = in_place_marker_path(smm_dir, name)
    if not holder.exists():
        return _legacy_verdict(marker)

    fd = in_place_locks.probe_holder_lock(holder)
    if fd is None:
        return _Verdict(_LIVE, None)  # held by a live supervisor (or unopenable)

    # The lock is free: its supervisor is gone. Only the child can still speak.
    child = _child_pid(marker)
    if child is not None and _probe_pid(child) is not False:
        # Alive, or UNADJUDICABLE (EPERM, another uid, a value os.kill cannot
        # take). Neither is proof of death, and refusing to delete a marker we
        # cannot prove dead is the only direction that cannot destroy a live
        # teammate's state.
        in_place_locks.release_holder_lock(fd)
        return _Verdict(_LIVE, None)
    return _Verdict(_DEAD, fd)


def _legacy_verdict(marker: Path) -> _Verdict:
    """A marker with NO lock beside it: a pre-lock artifact — or a free name.

    It keeps the OLD pid adjudication, verbatim, and that is a deliberate
    migration decision rather than an oversight. Such a marker is auto-reaped
    TODAY once its supervisor and child are both proven dead. Calling it merely
    "unadjudicable" and never reaping it would turn the wedge this story fixes
    from rare into CERTAIN for every marker in existence at upgrade time — a worse
    bug than the one being fixed, shipped to every user.

    No migration, no sweep: legacy markers age out on the first respawn (which
    always creates the lock before publishing the marker).

    It does NOT then become dead code, and must not be deleted as such. "No lock
    file" is also the state a human produces by rm'ing a holder lock, and this
    fallback is the ONLY thing that then keeps the name refused while its
    teammate is still alive (see the module docstring: the lock and the marker
    cover each other). Delete it and `rm *.lock` means two `claude`s in one
    checkout.
    """
    if not marker.exists() and not marker.is_symlink():
        return _Verdict(_DEAD, None)  # no marker, no lock: the name is FREE
    tokens = _read_tokens(marker)
    if tokens is None:
        return _Verdict(_UNPROVEN, None)  # symlinked, unreadable, not UTF-8
    try:
        pids = [int(t) for t in tokens]
    except ValueError:
        return _Verdict(_UNPROVEN, None)  # a legacy NAME-content marker
    if not pids:
        return _Verdict(_UNPROVEN, None)  # empty: not alive, not proof of death
    probes = [_probe_pid(p) for p in pids]
    if any(p is True for p in probes):
        return _Verdict(_LIVE, None)
    if all(p is False for p in probes):
        return _Verdict(_DEAD, None)  # every recorded process PROVEN dead
    return _Verdict(_UNPROVEN, None)


def _child_pid(marker: Path) -> int | None:
    """The `claude` child's pid — the second token — or None when the marker
    records none (the window before Popen returns, or a corrupt marker).

    None means the OR-leg simply contributes nothing and the holder lock decides
    alone. That keeps a corrupt marker with a FREE lock reapable: its supervisor
    is provably gone, and leaving it would wedge the name forever, which is the
    failure mode we are here to remove.
    """
    tokens = _read_tokens(marker)
    if tokens is None or len(tokens) < 2:
        return None
    try:
        return int(tokens[1])
    except ValueError:
        return None


def _read_tokens(path: Path) -> list[str] | None:
    """The marker's whitespace-separated tokens, or None if unreadable.

    O_NOFOLLOW mirrors the writer: a symlinked marker is not something we wrote,
    and read_text() would follow it — so a symlink planted at a marker path, with
    a LIVE pid behind it, could SUPPRESS the accept gate. Refusing to read it
    fails in the safe direction (reads dead ⇒ the gate fires).

    None on anything unreadable — vanished, symlinked, non-UTF-8 (a
    UnicodeDecodeError is a ValueError, which is why the except clause is not
    OSError alone). Letting those escape would crash the Stop hook, and a crashed
    gate never fires at all.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        chunks: list[bytes] = []
        while chunk := os.read(fd, 4096):
            chunks.append(chunk)
        return b"".join(chunks).decode().split()
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


def _probe_pid(pid: int) -> bool | None:
    """True = alive, False = PROVEN dead, None = cannot adjudicate.

    Still here, and still three-state, but its job has NARROWED: it no longer
    adjudicates the supervisor (the lock does that). It answers the child-pid
    OR-leg, and the legacy fallback. Its three states map onto the OR-leg exactly:
    alive ⇒ LIVE; proven dead ⇒ contributes nothing, the lock decides;
    unadjudicable ⇒ LIVE, because we will not delete what we cannot prove dead.

    POSIX-only: os.kill(pid, 0) is a liveness probe here, but on Windows it would
    terminate the target. The plugin is already POSIX (flock, bash preloads), so
    this is a note, not a branch.
    """
    if pid <= 0:
        # os.kill(0, 0) signals our OWN process group and SUCCEEDS; negative pids
        # are process-GROUP targets. Neither is a pid we wrote, so this is
        # corruption: not alive, but not proof of death either.
        return None
    try:
        os.kill(pid, 0)
    except OverflowError:
        # int() is arbitrary-precision but os.kill needs a C int. OverflowError is
        # an ArithmeticError, so it escapes the OSError clauses below and would
        # CRASH the Stop hook — and a crash means the gate never fires at all.
        return None
    except ProcessLookupError:
        return False  # proven dead
    except OSError:
        # PermissionError: the pid EXISTS but is owned by another uid, so it is
        # not our teammate (which runs as us) — unadjudicable, and certainly not
        # proof of death.
        return None
    return True


def in_place_teammate_from_env(smm_dir: Path, env_name: str | None) -> bool:
    """True when env_name names a live in-place teammate (marker present).

    Wraps the env-name-not-None + in_place_marker_exists check the three call
    sites (identity, pre_tool_skill, commit_handling) rolled by hand. Caller-side
    id-shape validation (is_teammate_agent_id) and smm_dir resolution stay at the
    call sites, which differ.
    """
    return env_name is not None and in_place_marker_exists(smm_dir, env_name)
