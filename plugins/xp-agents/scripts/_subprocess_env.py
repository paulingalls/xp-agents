#!/usr/bin/env python3
"""Shared helpers for subprocess-running a project-declared command.

``worktree_bootstrap.run_bootstrap`` (``stack.worktree_bootstrap``) and
``verify_acceptance`` (``acceptance_execution`` / ``--sprint`` commands) both
shell out to a command the PROJECT declares, and both need the same two
things: a positive-int timeout read from an env var with a fallback default,
and a child env carrying the resolved SMM_DIR so a ``$SMM_DIR``-referencing
command resolves it correctly regardless of the child's own cwd. Before this
module existed each site hand-rolled its own near-identical copy of both.

``worktree_bootstrap.run_bootstrap`` and ``worktree_teardown.run_teardown``
also share the process-group-aware invocation below: ``shell=True`` +
``timeout`` alone reaps only the shell, leaving alive any child the declared
command backgrounds or forks — exactly the orphans a teardown command exists
to kill. ``start_new_session=True`` puts the shell and its descendants in a
new process group so a timeout can ``killpg`` all of them at once.

It also owns the stderr-first output convention
(``combine_streams``/``combined_output`` and their bounded
``tail_streams``/``tailed_output``), which every relay of a subprocess's
diagnostics routes through: the close push relay, the lint runners, and
worktree bootstrap/teardown/differential. Those live here rather than beside
any one relay because none of them is about branch merges, worktrees or lint
in particular — they are about what a child process said.

Pure stdlib, no SMM/scripts imports — either caller can import this leaf
module with zero cycle risk.
"""

import contextlib
import os
import signal
import subprocess
from pathlib import Path

# How long to drain the pipes after killing the group. Bounded on purpose:
# see the drain comment in run_in_new_process_group.
_DRAIN_TIMEOUT_S = 5


def combine_streams(stderr: str, stdout: str) -> str:
    """Both streams, stderr first, newline-separated.

    A failed `git push` reports its own error on stderr while the pre-push hook's
    output — usually the actual cause — goes to stdout. Relaying one stream discards
    half the diagnosis.

    Takes the PAIR, not a `CompletedProcess`, so that the relays holding neither —
    bytes decoded per-stream, streams tailed before joining, a killed child's
    `TimeoutExpired` — spell the order here rather than each for itself.
    """
    if stderr and stdout and not stderr.endswith("\n"):
        stderr += "\n"
    return stderr + stdout


def combined_output(r: subprocess.CompletedProcess[str]) -> str:
    """Both captured streams of a completed process — see `combine_streams`."""
    return combine_streams(r.stderr or "", r.stdout or "")


# A failing `git push` now carries the whole suite's report on stdout, and
# untailed that buries git's own one-line error in hundreds of KB.
RELAY_TAIL_CHARS = 4000


def _tail(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def tail_streams(stderr: str, stdout: str, limit: int = RELAY_TAIL_CHARS) -> str:
    """`combine_streams`, each stream capped at its last *limit* chars.

    Per stream, never after the join, where a long stdout evicts the stderr. A
    slice that dropped a head is prefixed `...`, so a reader can tell a tail
    from a whole output instead of reading a mid-sentence start as the first
    word the command said.
    """
    return combine_streams(_tail(stderr, limit), _tail(stdout, limit))


def tailed_output(r: subprocess.CompletedProcess[str]) -> str:
    """`combined_output`, bounded — see `tail_streams`."""
    return tail_streams(r.stderr or "", r.stdout or "")


class TimedOutWithOutput(subprocess.TimeoutExpired):
    """``TimeoutExpired`` carrying the child's DECODED output.

    ``TimeoutExpired.stdout``/``.stderr`` are typed — and on some paths
    populated — as ``bytes`` even when the process ran with ``text=True``,
    so a caller that f-strings them prints ``b'...'`` at the operator. These
    two attributes are always ``str``. Subclassing keeps every existing
    ``except subprocess.TimeoutExpired`` working unchanged.
    """

    def __init__(self, cmd: str, timeout: float, out: str = "", err: str = ""):
        super().__init__(cmd, timeout)
        self.text_stdout = out
        self.text_stderr = err


def run_in_new_process_group(
    command: str, cwd: str, timeout: int, env: dict[str, str], capture: bool = True
) -> subprocess.CompletedProcess:
    """Run *command* via the shell, killing its whole process group on timeout.

    Raises ``subprocess.TimeoutExpired`` if the command doesn't finish in
    time — the process group has already been killed by then, so callers
    never block on a hung descendant's pipes. Raise-vs-swallow policy for
    both ``TimeoutExpired`` and a non-zero exit is each caller's own.

    ``capture=False`` inherits the parent's stdio instead of piping it, for
    the one caller (``verify_acceptance``'s ``--story`` gate) an operator
    WATCHES: capturing an hour-long acceptance suite would blank the screen
    until it finished. The kill-the-group guarantee is unaffected — it comes
    from ``start_new_session`` + ``killpg``, not from owning the pipes — but
    ``returncode`` is then the only thing a caller learns, since the returned
    ``stdout``/``stderr`` (and a timeout's drained output) are ``None``.
    Deliberately a boolean and not pluggable stdio targets: no caller wants a
    third destination, and the alternative — a second hand-rolled
    ``Popen(start_new_session=True)`` at the streaming site — is exactly the
    duplication this module exists to remove.
    """
    pipe = subprocess.PIPE if capture else None
    proc = subprocess.Popen(
        command,
        shell=True,  # noqa: secret
        cwd=cwd,
        stdout=pipe,
        stderr=pipe,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException as exc:
        # BaseException, not just TimeoutExpired, and the width is the point.
        # start_new_session detaches the child from the controlling terminal,
        # so a Ctrl-C no longer reaches it as part of the terminal's group.
        # Catching only TimeoutExpired would let KeyboardInterrupt propagate
        # straight past the one killpg that can still reach the group, leaving
        # the whole declared-command tree running detached — a NEW orphan door
        # opened by the very flag that closes the timeout one. TimeoutExpired
        # is a subclass, so the timeout path below is unchanged.
        #
        # Kill the whole process group (negative pgid), not just the shell
        # `proc` points at — start_new_session made the shell its leader, so
        # its pgid equals its pid. A plain proc.kill() would leave any
        # backgrounded/forked descendant alive.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        # Bounded, because "never blocks" has to survive a descendant that
        # setsid'd its way OUT of the group and still holds the pipe: killpg
        # cannot reach it, and an unbounded drain here would hang the one
        # path that must not.
        try:
            drained_out, drained_err = proc.communicate(timeout=_DRAIN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            drained_out, drained_err = "", ""
        # Hand the child's output back on the timeout path — a caller that can
        # only report "timed out after 120s" tells the operator nothing about
        # WHY. Re-raised as the str-typed subclass rather than mutating the
        # original, whose stdout/stderr are bytes-typed.
        if isinstance(exc, subprocess.TimeoutExpired):
            raise TimedOutWithOutput(
                command, timeout, drained_out or "", drained_err or ""
            ) from exc
        raise
    return subprocess.CompletedProcess(
        command, proc.returncode, stdout=stdout, stderr=stderr
    )


def _env_int(name: str, default: int) -> int:
    """Env var *name* as a positive int, or *default*.

    Only a POSITIVE value overrides: ``timeout=0`` makes
    ``run_in_new_process_group`` raise ``TimeoutExpired`` before the command
    has run at all, so a zero/negative override would silently convert every
    declared command into an immediate false failure that never actually ran.
    Zero, negative, unset, and unparseable text all fall back to *default* —
    the same fallback trio every call site needs, now defined once.
    """
    raw = os.environ.get(name)
    if raw:
        try:
            seconds = int(raw)
        except ValueError:
            return default
        if seconds > 0:
            return seconds
    return default


def smm_child_env(smm_dir: Path) -> dict[str, str]:
    """Child env for a subprocess whose command may reference $SMM_DIR.

    Injects the RESOLVED ABSOLUTE path: a declared command often ``cd``s
    before referencing ``$SMM_DIR``, or otherwise runs with a cwd that
    differs from the parent's — a relative value would then resolve against
    the CHILD's cwd instead of the parent's, and the command's own
    ``$SMM_DIR`` reference would silently miss.
    """
    return {**os.environ, "SMM_DIR": str(smm_dir.resolve())}
