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

import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_DIR = Path("/tmp")
_LOG_ROOT = _DEFAULT_LOG_DIR / "xp-agents-teammates"


def _path_token(value: str | None) -> str | None:
    """Reduce *value* to one safe path segment, or None if there is nothing left.

    The sprint id reaches us from sprint.json, where it is schema-checked as a
    string but NOT as a path. A `/` or a `..` in it would walk the namespace out
    of the per-project dir — into a sibling project's prompts, or out of /tmp
    entirely. Keep only characters that cannot traverse, and treat a token that
    survives as nothing (``..``, ``/``, blank) as absent.
    """
    if value is None:
        return None
    safe = "".join(c for c in value if c.isalnum() or c in "._-")
    return safe.strip("._-") or None


def safe_name(name: str) -> str:
    """*name*, verified to be ONE path segment that cannot traverse. Else raises.

    The sprint id was sanitized against traversal (`_path_token`) and the
    teammate NAME — which lands in the same directory, as the filename half of
    both the prompt path and the tee log path — was passed through raw. It is CLI
    input (`spawn_teammate --name`, authored by /xp-assign), so `--name
    ../../../etc/x` walked the prompt file straight out of the per-project
    namespace, and the same raw value is joined into the worktree path, the
    `.story-assignment-<name>` marker and the in-place marker. One guard at the
    boundary covers all five.

    VERIFIES rather than sanitizes: a silent rewrite would resolve to a different
    path than the one the caller believes it asked for, and the lead and the
    teammate must meet at the SAME prompt file. A name that is not already safe
    is a bug in the caller, so say so.
    """
    if _path_token(name) != name:
        raise ValueError(
            f"unsafe teammate name {name!r}: must be one path segment of "
            "alphanumerics, '.', '_' or '-' (it becomes a filename in the "
            "prompt/log namespace and a directory in the worktree path)"
        )
    return name


def _project_dir(smm_dir: str | Path, sprint_id: str | None) -> Path:
    """Return the /tmp namespace directory for *smm_dir* within *sprint_id*.

    Teammate names (``worktree-story-001``) and story ids repeat across
    projects, so a flat ``/tmp/<name>.log`` or ``/tmp/prompt-<id>.txt`` collides
    when two xp-agents sessions in different projects spawn same-named teammates.
    SMM lives at ``${CLAUDE_PLUGIN_DATA}/{project-id}/smm/``, so the SMM parent's
    name is a per-project token — namespace teammate files under it to keep them
    isolated while preserving /tmp's ephemerality and discoverability.

    Story ids repeat across SPRINTS for the identical reason, and a stale
    prompt is far likelier to come from last sprint's story-003 than from
    another project's: nothing invalidates a prompt file, so sprint-116's
    story-003 prompt would otherwise sit exactly where sprint-117's story-003
    spawns from — a plausible prompt for the WRONG story. So the sprint id
    EXTENDS the project token rather than replacing it: two projects' sprint-117
    must still stay apart.

    *sprint_id* is REQUIRED, never defaulted: spawn_teammate resolves it once
    and passes it to every call site. An optional arg would let a missed site
    silently resolve the OLD (project-only) path — the lead writing the prompt
    to one path while spawn reads another, i.e. a spawn on an EMPTY prompt,
    which is worse than the stale-prompt bug this scoping exists to kill. None
    is a legitimate VALUE (no sprint: free branch, ad-hoc teammate) and degrades
    to the project-only namespace; it just may not be a default.

    Single source of truth for the namespace token shared by logs and prompts.
    """
    project = _LOG_ROOT / Path(smm_dir).resolve().parent.name
    token = _path_token(sprint_id)
    return project / token if token else project


def project_log_dir(smm_dir: str | Path, *, sprint_id: str | None) -> Path:
    """Return the sprint-scoped forensic-log directory for *smm_dir*."""
    return _project_dir(smm_dir, sprint_id)


def project_prompt_path(
    smm_dir: str | Path, name: str, *, sprint_id: str | None
) -> Path:
    """Return the deterministic prompt-file path for *name* in *sprint_id*.

    The orchestrator writes each teammate's spawn prompt here before invoking
    spawn_teammate. Prompt files, like logs, are keyed on the teammate name,
    which repeats across projects AND across sprints — so they share the
    namespace and the collision argument of ``_project_dir``. Co-locate the
    prompt beside the log under that one dir.

    Raises ValueError on a name that could escape the namespace — see
    ``safe_name``. This is the leaf guard; ``spawn_teammate.main`` refuses the
    same name at the boundary, BEFORE any side effect.
    """
    return _project_dir(smm_dir, sprint_id) / f"{safe_name(name)}.prompt.txt"


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
    on_spawn: Callable[[int], None] | None = None,
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

    ``on_spawn``, when given, is called with the child's pid as soon as it
    exists. This process is only a TEE around that child: it holds the child's
    stdout pipe and waits, but the child is launched with a plain ``Popen`` (no
    ``start_new_session``), so a signal delivered to THIS pid does not propagate
    to it — the child can outlive us, reparented to init. Anything recording
    "is the teammate still running?" must therefore know the child's pid, not
    just ours. The callback runs before the read loop so no observer can catch
    the child running while the record still says otherwise.

    Returns ``stdout_broken``: True when the downstream stdout consumer (the
    output filter) closed mid-stream. The teammate still ran to completion and
    the log is intact, but the filter that owns the report/completion/
    coordination-clear did not finish — the caller must skip the rc=0 promote.
    """
    log_path = log_dir / f"{safe_name(name)}.log"
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
    if on_spawn is not None:
        try:
            on_spawn(proc.pid)
        except BaseException:
            # If the child's pid cannot be recorded, nothing can later prove the
            # child alive -- so a reap would delete the marker of a LIVE teammate
            # and demote it to lead, the failure this marker exists to prevent.
            # Kill the child rather than leave it running unrecorded, and fail
            # loud. Note the finally below does NOT kill: it stops the watchdog
            # and then proc.wait()s, so merely raising past it would deadlock on
            # a child whose stdout nobody is reading.
            proc.kill()
            proc.wait()
            raise

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
                try:
                    log_file.write(line)
                    log_file.flush()
                except OSError as exc:
                    # The tee is best-effort. A mid-stream log write failure
                    # (e.g. full disk) must not propagate — that would stop
                    # draining proc.stdout and deadlock a healthy child on a
                    # full pipe. Drop the tee and keep draining.
                    sys.stderr.write(
                        f"WARN: tee log write failed ({exc}); continuing without tee\n"
                    )
                    with contextlib.suppress(OSError):
                        log_file.close()
                    log_file = None
    finally:
        watchdog.stop()
        if log_file is not None:
            log_file.close()
        proc.wait()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return stdout_broken
