#!/usr/bin/env python3
"""Run a teammate subprocess with a stdout/log tee and a liveness watchdog.

Extracted from spawn_teammate.py (which owns command construction, worktree
and marker lifecycle, and the story promote) to keep both files under the
size cap. This module is the leaf "runner": given a command, it streams the
child's stdout to both this process' stdout and a project-scoped forensic
log, guards liveness with a daemon watchdog, and reports whether the
downstream stdout consumer closed mid-stream.

Self-contained — imports no SMM/plugin modules, so it needs no sys.path
bootstrap.
"""

import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_DIR = Path("/tmp")
_LOG_ROOT = _DEFAULT_LOG_DIR / "xp-agents-teammates"


def project_log_dir(smm_dir: str | Path) -> Path:
    """Return the project-scoped forensic-log directory for *smm_dir*.

    Teammate names (``worktree-story-001``) repeat across projects, so a flat
    ``/tmp/<name>.log`` collides when two xp-agents sessions in different
    projects spawn same-named teammates. SMM lives at
    ``${CLAUDE_PLUGIN_DATA}/{project-id}/smm/``, so the SMM parent's name is a
    per-project token — namespace logs under it to keep them isolated while
    preserving /tmp's ephemerality and discoverability.
    """
    return _LOG_ROOT / Path(smm_dir).resolve().parent.name


# Watchdog: max silence (no .ping()) before SIGTERM. 900s = 15 min,
# sized to clear the longest legitimate thinking-on-large-context gap
# observed historically (~10 min on 256K-token inputs). Hard-coded;
# the next retro recalibrates if 900s false-positives or proves slow.
_WATCHDOG_TIMEOUT_S = 900
_WATCHDOG_POLL_INTERVAL_S = 5
# Grace period between SIGTERM and SIGKILL — SIGTERM may be ignored
# while the child is blocked in a C-level recv() on the API socket
# (the suspected hang mode); SIGKILL guarantees recovery fires.
_WATCHDOG_KILL_GRACE_S = 10


class _ActivityWatchdog:
    """Terminates *proc* when no .ping() arrives for *timeout_s* seconds.

    The run_with_tee main loop calls .ping() on each line read from the
    subprocess. If pings stop (because the spawned ``claude -p`` has
    gone silent), the watchdog calls ``proc.terminate()``, waits up to
    ``_WATCHDOG_KILL_GRACE_S`` for it to exit, then escalates to
    ``proc.kill()``. The main loop then sees stdout EOF, ``proc.wait()``
    returns a non-zero rc, and ``run_with_tee`` raises
    ``CalledProcessError`` as it does on any non-zero exit. The
    existing rc!=0 recovery path in main() takes over (story stays
    in-progress, prompt file preserved for re-spawn).

    *timeout_s*, *poll_interval_s*, and *kill_grace_s* default to
    ``None`` and resolve to the module constants at call time. Tests
    patch the constants; production callers omit all three args.
    """

    def __init__(
        self,
        proc,
        name: str,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
        kill_grace_s: float | None = None,
    ):
        self._proc = proc
        self._name = name
        self._timeout = _WATCHDOG_TIMEOUT_S if timeout_s is None else timeout_s
        self._poll = (
            _WATCHDOG_POLL_INTERVAL_S if poll_interval_s is None else poll_interval_s
        )
        self._kill_grace = (
            _WATCHDOG_KILL_GRACE_S if kill_grace_s is None else kill_grace_s
        )
        self._last_activity = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"watchdog-{name}"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Bound test-process thread accumulation; daemon=True still keeps
        # production exits clean if join misses.
        self._thread.join(timeout=self._poll + 0.1)

    def ping(self) -> None:
        # Single attribute write — atomic under the GIL; no lock needed.
        # Worst case is one extra poll cycle before termination.
        self._last_activity = time.monotonic()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            if time.monotonic() - self._last_activity > self._timeout:
                sys.stderr.write(
                    f"WATCHDOG: {self._name} silent >{self._timeout}s — terminating\n"
                )
                try:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=self._kill_grace)
                    except subprocess.TimeoutExpired:
                        sys.stderr.write(
                            f"WATCHDOG: {self._name} did not exit on SIGTERM "
                            f"within {self._kill_grace}s — SIGKILL\n"
                        )
                        self._proc.kill()
                except (OSError, subprocess.SubprocessError):
                    # Expected failure modes: process already exited
                    # (terminate/kill OSError), or wait raises a
                    # SubprocessError. Don't catch broader exceptions —
                    # an AttributeError from a bogus proc must crash
                    # visibly in tests rather than silently leak.
                    pass
                return


def run_with_tee(
    cmd: list[str],
    cwd: str,
    env: dict,
    stdin,
    name: str,
    log_dir: Path = _DEFAULT_LOG_DIR,
) -> bool:
    """Run *cmd*, mirroring stdout (and merged stderr) to both this process'
    stdout and ``<log_dir>/<name>.log``. Caller passes the worktree name
    (e.g. ``worktree-story-001``) so the log file lands at
    ``<log_dir>/worktree-story-001.log``.

    The on-disk log preserves output up to the termination point so a
    stuck teammate can be inspected forensically. If the log file
    can't be opened, the spawn proceeds without teeing — investigation
    aid is best-effort, not load-bearing.

    Re-spawns of the same teammate name *append* with a session header so
    the forensic record from a prior hang survives a kill + retry.

    A liveness watchdog runs in a daemon thread alongside this loop:
    each line read pings it; if pings stop for ``_WATCHDOG_TIMEOUT_S``
    seconds, the watchdog terminates the subprocess (SIGTERM, then
    SIGKILL after a grace period). The main loop then sees stdout
    EOF, ``proc.wait()`` returns the signal exit code, and this
    function raises ``CalledProcessError`` — same recovery shape as
    any other non-zero exit. Without the watchdog, a child blocked
    indefinitely inside an HTTPS POST to the model API could keep
    the orchestrator waiting forever.

    Raises ``subprocess.CalledProcessError`` on non-zero exit so callers
    keep the prior ``check=True`` failure semantics.

    Returns ``stdout_broken``: True when the downstream stdout consumer (the
    output filter) closed mid-stream. The teammate still ran to completion and
    the log is intact, but the filter that owns the report/completion/
    coordination-clear did not finish — the caller must skip the rc=0 promote.
    """
    log_path = log_dir / f"{name}.log"
    log_file = None
    try:
        log_file = log_path.open("a")
        log_file.write(
            f"\n===== spawn {name} {datetime.now(timezone.utc).isoformat()} =====\n"
        )
        log_file.flush()
    except OSError as exc:
        sys.stderr.write(
            f"WARN: tee log {log_path} unavailable ({exc}); spawning without tee\n"
        )

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )
    watchdog = _ActivityWatchdog(proc, name)
    watchdog.start()
    stdout_broken = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            watchdog.ping()
            if not stdout_broken:
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except BrokenPipeError:
                    # Downstream (the output filter) closed. Stop writing to
                    # stdout but KEEP draining proc.stdout to the log — else
                    # claude -p blocks on a full stdout pipe and the healthy
                    # teammate deadlocks. The raw log stays the source of truth.
                    stdout_broken = True
            if log_file is not None:
                log_file.write(line)
                log_file.flush()
    finally:
        watchdog.stop()
        if log_file is not None:
            log_file.close()
        proc.wait()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return stdout_broken
