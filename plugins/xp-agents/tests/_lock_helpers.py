"""Lock-holding helpers for tests that exercise events.lock contention.

Two contextmanager flavors capture the patterns previously duplicated
across 6 test sites:

- ``held_events_lock(smm_dir, *, budget=1)`` — open + LOCK_EX held for the
  duration of the with-block. Patches ``_append_impl.LOCK_TIMEOUT_SECONDS``
  down so the timeout fires fast. Use when the assertion is
  "raises LockTimeoutError" (the budget is the trigger, not a wait).
- ``briefly_held_lock(smm_dir, *, hold=0.3, budget=2)`` — spawns a thread
  that holds the flock for ``hold`` seconds, then releases. Patches the
  budget larger than ``hold``. Use when the assertion is "completes
  within budget" (the budget must outlast the hold).

Both compose with other context managers (commit mocks, assertRaises) so
existing test sites can wrap them inside parenthesized ``with`` blocks.
"""

import contextlib
import fcntl
import threading
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import _append_impl

# Watchdog timeouts — guard against test-infra failure (holder thread
# never starts, never exits). Generous enough that healthy runs never
# hit them; small enough that broken runs fail fast.
_HOLDER_STARTUP_TIMEOUT = 2.0
_HOLDER_JOIN_TIMEOUT = 5.0


@contextlib.contextmanager
def held_events_lock(smm_dir: Path, *, budget: int = 1) -> Iterator[None]:
    """Hold ``events.lock`` exclusively for the with-block.

    Patches ``LOCK_TIMEOUT_SECONDS`` down to ``budget`` so callers under
    contention raise ``LockTimeoutError`` quickly — the assertion is
    "raises", not "waits N seconds".
    """
    lock_fd = open(smm_dir / "events.lock", "a")  # noqa: SIM115
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        with mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", budget):
            yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


@contextlib.contextmanager
def briefly_held_lock(
    smm_dir: Path, *, hold: float = 0.3, budget: int = 2
) -> Iterator[None]:
    """Hold ``events.lock`` in a thread for ``hold`` seconds, then release.

    Patches ``LOCK_TIMEOUT_SECONDS`` to ``budget`` so a waiter inside the
    with-block clears contention and succeeds — the assertion is
    "budget outlasts hold", not "wait the full hold". ``budget`` must
    exceed ``hold``; otherwise the patched waiter would time out before
    the holder thread releases, defeating the test's purpose.
    """
    if budget <= hold:
        raise ValueError(f"budget ({budget}s) must exceed hold ({hold}s)")
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_briefly() -> None:
        fd = open(smm_dir / "events.lock", "a")  # noqa: SIM115
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            lock_acquired.set()
            # Releases at ``hold`` seconds OR when ``release_lock`` is
            # set in the finally below — whichever comes first.
            release_lock.wait(timeout=hold)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    holder = threading.Thread(target=hold_briefly)
    holder.start()
    try:
        if not lock_acquired.wait(timeout=_HOLDER_STARTUP_TIMEOUT):
            raise RuntimeError("holder thread failed to acquire events.lock")
        with mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", budget):
            yield
    finally:
        release_lock.set()
        holder.join(timeout=_HOLDER_JOIN_TIMEOUT)
        if holder.is_alive():
            raise RuntimeError(
                "holder thread did not exit within the join timeout — "
                "possible flock leak"
            )
