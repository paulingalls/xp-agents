#!/usr/bin/env python3
"""The two in-place locks. They do unrelated jobs; do not merge them.

THE HOLDER LOCK (`.in-place-holder-{name}.lock`, one per name)
    Taken LOCK_NB by the supervisor and held for the WHOLE episode. Its being
    held IS the liveness verdict, and the reason is the kernel: a process that
    dies — cleanly, on SIGTERM, on SIGKILL, on a power-off — has its fds closed
    for it, so its flock is released whether or not any of its code ran. No pid
    bookkeeping can promise that. A pid can also be RECYCLED, and a recycled pid
    reads LIVE forever, wedging the name against every respawn. A lock cannot be
    recycled.

    This is why `flock_with_timeout` CANNOT implement it: that helper documents
    "the lock fd is intentionally not yielded" and releases at context exit. The
    holder lock is an fd that must OUTLIVE any `with` block — it is handed to the
    supervisor and released in its `finally`, an episode later. Hence this module.

    The fd stays CLOEXEC (Python's default since PEP 446, and no `pass_fds`), so
    the `claude` child does NOT inherit it. It could: an flock belongs to the open
    file DESCRIPTION, not the process, so an inherited fd would keep the lock held
    for as long as the child lives — which would close the orphaned-child hole
    outright. We DECLINE that: it would couple a safety gate to the fd-handling of
    a third-party binary we do not control and whose semantics are undocumented.
    The child-pid OR-leg in in_place_marker covers that case instead.

THE DOOR MUTEX (`.in-place.lock`, one per SMM dir)
    Held for MICROSECONDS, by every door that takes a holder lock it does not
    intend to KEEP — the reap proving a holder dead, the teardown releasing one.
    For the width of such a hold, that door is indistinguishable, to a claimant
    testing the same lock, from a live teammate. The mutex makes those transient
    holds invisible — WHILE IT IS HELD, and no further. A reap that could not take
    it answers anyway (see in_place_marker), and its probe still takes a holder
    lock; a claimant racing that probe can read the transient hold as LIVE and
    refuse a name it could have taken. That is the price of answering anyway, and
    it is paid in the safe direction: a loud refusal, never a reap.

    Deadlock proof: the mutex is the ONLY lock anyone ever BLOCKS on. Every holder
    lock is acquired LOCK_NB, and nobody blocks while holding the mutex.

    It can fail (a wedged sibling, a 10s SIGALRM budget). `door_mutex` therefore
    never raises — it yields False — because the doors disagree about what to do
    then: the reap must ANSWER ANYWAY (a Stop gate that crashes never fires, and
    one that blanket-answers "nobody is live" certifies a half-written tree),
    while the claim must REFUSE (two claimants both publishing would put two
    `claude` processes in one checkout). Each door states its own rule.
"""

import contextlib
import fcntl
import os
import sys
from contextlib import AbstractContextManager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import marker_names
from _try_flock import try_flock


def holder_lock_path(smm_dir: Path, name: str) -> Path:
    """The per-name holder lock. Never matches the marker glob (marker_names)."""
    return smm_dir / marker_names.IN_PLACE_HOLDER.format(name=name)


def door_mutex(smm_dir: Path) -> AbstractContextManager[bool]:
    """Hold the door mutex for the block. Yields True when held, False when not.

    The whole of the shape — never raising on a failed acquire, wrapping only the
    acquire and never the body — now lives in `_try_flock.try_flock`, which the
    coordination file shares. This stays as the NAME for the door's own lock path
    so callers keep reading `with door_mutex(smm_dir) as held:`.

    No `on_giveup`: nothing here needs the cause. Each caller already decides what
    an unavailable door means, and none of them logs.
    """
    return try_flock(smm_dir / marker_names.IN_PLACE_DOOR_LOCK)


def probe_holder_lock(path: Path) -> int | None:
    """Take an EXISTING holder lock, LOCK_NB. The liveness test itself.

    Returns the fd when the lock was FREE — meaning its holder is dead, and we
    now hold it, so the caller may reap SAFELY (nobody can be publishing under
    that name while we hold it). Returns None when the lock is HELD (a live
    teammate) or unopenable (never proof of death).

    O_CREAT is deliberately absent, and that absence is load-bearing. An
    unconditional create makes the missing lock file, acquires it trivially, reads
    DEAD, and reaps — which would collect every LEGACY (pre-lock) marker on sight,
    including one belonging to a live teammate running the old code. Callers test
    existence FIRST; a marker with no lock beside it is a legacy marker, not a
    dead one.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    return _try_lock(fd)


def create_holder_lock(path: Path) -> int | None:
    """Create the holder lock and take it — for a claim that has already
    adjudicated the name free. The only writer of a lock file."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        return None
    return _try_lock(fd)


def _try_lock(fd: int) -> int | None:
    """LOCK_NB on `fd`; close it and answer None if someone else holds it.

    Always LOCK_NB, never blocking: the door mutex is the only lock anyone waits
    on, which is what makes deadlock structurally impossible here. Note flock
    conflicts across open file DESCRIPTIONS even within one process, so a lock
    this process already holds correctly reads as held here too.
    """
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:  # BlockingIOError — someone holds it
        os.close(fd)
        return None
    return fd


def release_holder_lock(fd: int) -> None:
    """Drop a hold. Suppresses OSError so a flaky release never masks an
    in-flight exception (mirrors flock_with_timeout's own release)."""
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


# The names THIS process holds, and the fd holding each. An episode-scoped hold
# outlives every function call in the module, so it has to live somewhere; here,
# keyed by lock path so one process can hold several names (the test suite does)
# and so two SMM dirs never collide.
#
# This registry IS the ownership proof that the marker's CONTENT used to be. The
# old proof — "the first pid in the marker is mine" — could be forged by a writer
# against itself (write the marker, then read your own pid back as authority), and
# that forgery is exactly how a supervisor came to delete a LIVE teammate's
# marker. A lock cannot be forged: either you hold it or you do not.
_HELD: dict[Path, int] = {}


def keep_holder_lock(path: Path, fd: int) -> None:
    """Record `fd` as an episode-scoped hold — this process now OWNS the name."""
    _HELD[path] = fd


def holds_name(smm_dir: Path, name: str) -> bool:
    """True when THIS process holds `name`. The rewrite and the teardown gate on
    it: only the holder may rewrite its marker, and only the holder may remove
    it."""
    return holder_lock_path(smm_dir, name) in _HELD


def release_own_holder_lock(smm_dir: Path, name: str) -> None:
    """Release the hold we kept for `name`. Idempotent; never unlinks the lock
    FILE (the file is inert — it is the HOLD that means anything, and unlinking
    it under a live holder would let a claimant create a fresh one and take a
    name that is still in use)."""
    fd = _HELD.pop(holder_lock_path(smm_dir, name), None)
    if fd is not None:
        release_holder_lock(fd)
