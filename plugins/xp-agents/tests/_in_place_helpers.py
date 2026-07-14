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
import subprocess
import sys

# Every wait() on a child in this suite is BOUNDED. A test that blocks forever on
# a subprocess wedges CI with no output — which is not a hypothetical: a run once
# sat for 28 minutes waiting on a spawned process that had been killed out from
# under it. An unbounded wait is a defect even when the child is one we control.
CHILD_WAIT_TIMEOUT_S = 30


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
def live_pid():
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
