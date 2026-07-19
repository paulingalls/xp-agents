#!/usr/bin/env python3
"""Process-liveness helpers for the in-place teammate marker suites.

Every test that exercises a liveness verdict — the marker's reap, its claim, the
Stop gate that consumes it — needs real processes in known states. Hand-written
pids cannot express "alive", and a test that records only `os.getpid()` cannot
tell "this pid is alive" from "this pid is me".

Re-exported by conftest (by identity, as `_bases` / `_hook_inputs` are), so the
import surface for tests stays `from conftest import dead_pid, live_pid, ...`
and no test file changed when these moved out of conftest.

Note the tree has a SECOND, opposite convention — `_lock_helpers` is imported
direct from the sibling, never through conftest. Re-export is the right side of
that split here only because these four names were already reached via conftest;
a new helper with no existing import surface can go either way.
"""

import contextlib
import fcntl
import os
import select
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import in_place_locks
import marker_names
from _bases import _SCRIPTS_DIR, _SMM_DIR

# Watchdog for the door-mutex holder thread — generous enough that a healthy run
# never hits it, small enough that a broken one fails fast instead of wedging.
_MUTEX_STARTUP_TIMEOUT_S = 2.0

# How long the holder thread keeps the door mutex before giving up on it.
#
# This is NOT a free knob. It must comfortably exceed the real, UNPATCHED
# _append_impl.LOCK_TIMEOUT_SECONDS (10s), because a door in a SUBPROCESS sits out
# that whole budget before it concludes the mutex is unavailable — the in-process
# `budget` patch does not cross a process boundary. Set it below that and the
# mutex is released mid-wait, the starved door happily ACQUIRES it, and the test
# passes having exercised the uncontended path. held_door_mutex raises rather than
# let that go quiet, but the margin is what stops it happening at all.
_MUTEX_HOLD_TIMEOUT_S = 30.0

# Every wait() on a child in this suite is BOUNDED. A test that blocks forever on
# a subprocess wedges CI with no output — which is not a hypothetical: a run once
# sat for 28 minutes waiting on a spawned process that had been killed out from
# under it. An unbounded wait is a defect even when the child is one we control.
CHILD_WAIT_TIMEOUT_S = 30


def release_in_place_holds(smm_dir: Path) -> None:
    """Release every in-place name THIS process still holds under `smm_dir`.

    A claim takes a REAL holder lock and keeps it for the life of the process —
    which in production is a supervisor that then exits, and in a test is a worker
    that runs thousands more tests. Without this, every claiming test leaks an fd
    and leaves a flock held on a temp dir that is about to be deleted, and the
    module-global registry of held names grows for the whole run.

    Derives the names from the lock files on disk (the registry is private, and
    releasing a name we do not hold is a documented no-op), so it is safe to call
    unconditionally in a tearDown.
    """
    prefix, suffix = marker_names.IN_PLACE_HOLDER.split("{name}")
    for lock in smm_dir.glob(marker_names.IN_PLACE_HOLDER.format(name="*")):
        name = lock.name[len(prefix) : -len(suffix)]
        in_place_locks.release_own_holder_lock(smm_dir, name)


def reap(proc: subprocess.Popen, *, timeout: float = CHILD_WAIT_TIMEOUT_S) -> None:
    """Terminate and reap `proc`, escalating to SIGKILL, never blocking forever."""
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


def dead_pid() -> int:
    """Spawn and reap a child process, returning its now-dead pid.

    Reaping via wait() removes the process table entry, so os.kill(pid, 0)
    reliably raises ProcessLookupError afterward — no PID-reuse race within
    a single test's timeframe. Shared by every test that exercises a
    pid-liveness probe (in-place teammate marker, sprint stop gate).
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=CHILD_WAIT_TIMEOUT_S)
    return proc.pid


@contextlib.contextmanager
def live_pid() -> Iterator[int]:
    """Yield the pid of a real, LIVE child process; terminate + reap on exit.

    The other pole of dead_pid(). A liveness probe needs both to prove it
    discriminates: a test that only ever records its OWN pid (os.getpid())
    cannot tell "this pid is alive" from "this pid is me", and so cannot
    express the case where one recorded process is dead while ANOTHER is
    still running — the orphaned-teammate case.
    """
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        yield proc.pid
    finally:
        reap(proc)


# ---------------------------------------------------------------------------
# In-place HOLDERS — a real supervisor process that has taken the name.
#
# Liveness is now the holder lock, and a lock belongs to the process that took
# it. So a marker can only be made to read LIVE by a process that is STILL
# RUNNING and STILL HOLDING the lock — which no in-process fixture can fake: this
# test process could claim, but then it is the holder, and nothing it does to the
# marker file afterwards changes that verdict.
#
# Hence a subprocess. These are plain functions / contextmanagers, NOT
# @pytest.fixture (constraint fefb7ba988a0 — the suites stay importable under
# stdlib unittest, and CI runs no pytest), and they sit deliberately beside the
# live_pid / dead_pid they replace for the lock era.
# ---------------------------------------------------------------------------


class Holder(NamedTuple):
    """A supervisor subprocess that holds an in-place name.

    `child_pid` is the sleeper standing in for the `claude` child, recorded in
    the marker exactly as spawn_teammate's on_spawn records the real one, or
    None when the holder was asked for no child.
    """

    pid: int
    child_pid: int | None
    proc: subprocess.Popen

    def sigkill(self) -> None:
        """SIGKILL the supervisor and reap it — the ROUTINE cancel path.

        The signal that matters: Python installs no SIGKILL handler (none is
        possible), so the supervisor's `finally` does not run — it releases its
        holder lock only because the KERNEL closes its fds, and it leaks its
        marker. That asymmetry is the whole property the lock buys, and it is
        why `terminate()` would be the wrong verb here.

        Does NOT touch `child_pid`: a SIGKILL to the supervisor does not
        propagate to its child, which is precisely the case the OR-leg exists
        for. Tests that want the child dead too must kill it themselves.
        """
        self.proc.kill()
        self.proc.wait(timeout=CHILD_WAIT_TIMEOUT_S)


def _claim_script(smm_dir: Path, name: str, *, with_child: bool, then: str) -> str:
    """Source for a supervisor that claims `name`, then does `then`.

    It prints `CLAIMED <supervisor-pid> <child-pid>` once the name is TAKEN and
    the marker published, so a caller can wait on the claim having landed rather
    than on a sleep. (-1 stands for "no child", which is not a pid os.kill can
    be handed — see _probe_pid's pid<=0 guard.)
    """
    spawn_child = (
        "proc = subprocess.Popen([sys.executable, '-c', 'import time; "
        "time.sleep(300)'])\n"
        "child = proc.pid\n"
        "in_place_marker.rewrite_own_in_place_marker(smm, name, child)\n"
        if with_child
        else ""
    )
    return (
        "import os, subprocess, sys, time\n"
        f"sys.path[:0] = {[str(_SCRIPTS_DIR), str(_SMM_DIR)]!r}\n"
        "from pathlib import Path\n"
        "import in_place_marker\n"
        f"smm = Path({str(smm_dir)!r})\n"
        f"name = {name!r}\n"
        "child = -1\n"
        "in_place_marker.claim_in_place_marker(smm, name)\n"
        f"{spawn_child}"
        "print('CLAIMED', os.getpid(), child, flush=True)\n"
        f"{then}\n"
    )


def _await_claim(proc: subprocess.Popen) -> tuple[int, int | None]:
    """Read the holder's CLAIMED line under a BOUNDED wait.

    A bare readline() on a child that died before printing blocks until the pipe
    closes — and if it died holding a lock nothing closes it. select() bounds
    that: no line inside the budget is a test-infra failure, and it fails loudly
    rather than wedging CI (see CHILD_WAIT_TIMEOUT_S).
    """
    assert proc.stdout is not None
    ready, _, _ = select.select([proc.stdout], [], [], CHILD_WAIT_TIMEOUT_S)
    if not ready:
        raise RuntimeError("in-place holder never announced its claim")
    line = proc.stdout.readline().split()
    if not line or line[0] != "CLAIMED":
        raise RuntimeError(f"in-place holder failed to claim the name: {line!r}")
    child = int(line[2])
    return int(line[1]), (child if child > 0 else None)


@contextlib.contextmanager
def live_in_place_holder(
    smm_dir: Path, name: str, *, with_child: bool = False
) -> Iterator[Holder]:
    """Yield a LIVE Holder of `name` — the only way to make a marker read LIVE.

    The subprocess claims the name, keeps its holder lock (it is alive), and
    sleeps. On exit it is reaped, and any child it spawned is killed by pid: that
    child is a GRANDchild of this process, so it cannot be wait()ed here — it is
    reparented to init, which reaps it.
    """
    script = _claim_script(smm_dir, name, with_child=with_child, then="time.sleep(300)")
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
    )
    child_pid: int | None = None
    try:
        pid, child_pid = _await_claim(proc)
        yield Holder(pid, child_pid, proc)
    finally:
        if proc.poll() is None:
            reap(proc)
        # wait() reaps the process but does NOT close the pipe we opened for it,
        # so without this the read end leaks until the GC happens to collect the
        # Popen. `dead_in_place_holder` gets this for free from communicate().
        if proc.stdout is not None:
            proc.stdout.close()
        if child_pid is not None:
            _kill_by_pid(child_pid)


def dead_in_place_holder(smm_dir: Path, name: str) -> int:
    """Claim `name` in a subprocess that then DIES without cleaning up.

    `os._exit(0)` skips every `finally`, atexit hook and buffer flush — exactly
    what a SIGKILL does to the supervisor, which is the ROUTINE cancel path for a
    backgrounded spawn. So it leaves behind precisely what production leaves
    behind: a leaked marker, and a holder lock the KERNEL released. Returns the
    now-dead supervisor's pid.
    """
    script = _claim_script(smm_dir, name, with_child=False, then="os._exit(0)")
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
    )
    stdout, _ = proc.communicate(timeout=CHILD_WAIT_TIMEOUT_S)
    tokens = stdout.split()
    if not tokens or tokens[0] != "CLAIMED":
        raise RuntimeError(f"in-place holder failed to claim the name: {stdout!r}")
    return int(tokens[1])


def _kill_by_pid(pid: int) -> None:
    """SIGKILL a process we cannot wait() on (a grandchild). Idempotent."""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.kill(pid, signal.SIGKILL)


@contextlib.contextmanager
def held_door_mutex(smm_dir: Path, *, budget: int = 1) -> Iterator[None]:
    """Hold the in-place door mutex, so every door finds it UNAVAILABLE.

    Same shape as `_lock_helpers.held_events_lock` (which hardcodes events.lock):
    a THREAD takes the flock — signals only arm in the main thread, so the code
    under test must be the one that waits.

    flock conflicts across open file descriptions even within one process, so the
    mutex is unavailable to an in-process door AND to a subprocess one (the Stop
    hook), which is what the integration test needs.

    `budget` IS IN-PROCESS ONLY, and the asymmetry is worth stating because it is
    invisible at the call site: it patches `_append_impl.LOCK_TIMEOUT_SECONDS`,
    which a SUBPROCESS door does not read — that one re-imports the module and
    sits out its own timeout budget before its SIGALRM fires and `door_mutex`
    yields False. A subprocess door that wants a REAL but SHORT cross-process
    timeout must set the `XP_LOCK_TIMEOUT_SECONDS` env var on that subprocess
    (see `_effective_lock_timeout_seconds` in `_append_impl.py`) rather than
    relying on `budget` here — `_run_script_with_env` is the harness for that.
    Left unset, a subprocess door sits out the full real default budget (10s,
    measured), which is what made the subprocess mutex test the slowest in the
    suite before it started passing `XP_LOCK_TIMEOUT_SECONDS`. `_MUTEX_HOLD_TIMEOUT_S`
    must stay comfortably above whichever real budget (patched or default) the
    subprocess under test is actually using — see below for what happens if it
    does not.
    """
    from unittest import mock

    import _append_impl

    lock_fd = open(smm_dir / marker_names.IN_PLACE_DOOR_LOCK, "a")  # noqa: SIM115
    acquired = threading.Event()
    release = threading.Event()
    timed_out = threading.Event()

    def hold() -> None:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        acquired.set()
        if not release.wait(timeout=_MUTEX_HOLD_TIMEOUT_S):
            # We are about to drop the mutex while the body is STILL RUNNING, so
            # whatever it does next runs UNCONTENDED. That is not a slow test, it
            # is a test that silently stops testing anything — the door it wanted
            # to starve simply takes the mutex and takes the happy path. Recorded
            # here and raised at exit, because a thread cannot fail a test.
            timed_out.set()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        if not acquired.wait(timeout=_MUTEX_STARTUP_TIMEOUT_S):
            raise RuntimeError("holder thread failed to take the in-place door mutex")
        with mock.patch.object(_append_impl, "LOCK_TIMEOUT_SECONDS", budget):
            yield
    finally:
        release.set()
        holder.join(timeout=CHILD_WAIT_TIMEOUT_S)
        lock_fd.close()
        if holder.is_alive():
            raise RuntimeError("door-mutex holder thread did not exit — flock leak")
    # Outside the finally, so a real failure in the body reports itself rather
    # than being masked by this one.
    if timed_out.is_set():
        raise RuntimeError(
            f"the door mutex was released after {_MUTEX_HOLD_TIMEOUT_S}s, while the "
            "body was still running — the code under test ran UNCONTENDED, so this "
            "test proved nothing. It went green anyway; that is why this raises."
        )
