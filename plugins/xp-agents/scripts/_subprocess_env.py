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

Pure stdlib, no SMM/scripts imports — either caller can import this leaf
module with zero cycle risk.
"""

import os
import signal
import subprocess
from pathlib import Path


def run_in_new_process_group(
    command: str, cwd: str, timeout: int, env: dict[str, str]
) -> subprocess.CompletedProcess:
    """Run *command* via the shell, killing its whole process group on timeout.

    Raises ``subprocess.TimeoutExpired`` if the command doesn't finish in
    time — the process group has already been killed by then, so callers
    never block on a hung descendant's pipes. Raise-vs-swallow policy for
    both ``TimeoutExpired`` and a non-zero exit is each caller's own.
    """
    proc = subprocess.Popen(
        command,
        shell=True,  # noqa: secret
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole process group (negative pgid), not just the shell
        # `proc` points at — start_new_session made the shell its leader, so
        # its pgid equals its pid. A plain proc.kill() would leave any
        # backgrounded/forked descendant alive, and communicate() below could
        # then hang on a pipe those descendants still hold open.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(
        command, proc.returncode, stdout=stdout, stderr=stderr
    )


def _env_int(name: str, default: int) -> int:
    """Env var *name* as a positive int, or *default*.

    Only a POSITIVE value overrides: ``timeout=0`` makes ``subprocess.run``
    raise ``TimeoutExpired`` before the command has run at all, so a
    zero/negative override would silently convert every declared command
    into an immediate false failure that never actually ran. Zero, negative,
    unset, and unparseable text all fall back to *default* — the same
    fallback trio both call sites need, now defined once.
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
