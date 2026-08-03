#!/usr/bin/env python3
"""Stop whatever a teammate worktree started, before it's removed.

`worktree_bootstrap.py`'s mirror image. A project can declare
`stack.worktree_teardown` in its system_context; a caller runs it here,
against the worktree being removed, before the removal itself happens.

Leaf module: imports DOWN (system_context_store, _subprocess_env) and knows
nothing about worktree removal itself. `run_teardown` validates nothing
about `wt_path` — the caller owns deciding which worktree to tear down and
when; this module only knows how to run the declared command against it.
"""

import subprocess
import sys
from pathlib import Path

# See worktree_bootstrap.py's matching comment: an explicit statement, not a
# reorderable bare import, so isort can't hoist the smm import above it.
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import system_context_store

# See worktree_bootstrap.py's matching comment: _subprocess_env is a
# scripts/-local sibling, resolvable only once scripts/ is on sys.path.
sys.path.insert(0, str(Path(__file__).parent))

import _subprocess_env

# Stopping things is bounded work, unlike bootstrap's cold-install case — a
# hung teardown must not stall a worktree removal for minutes.
_DEFAULT_TEARDOWN_TIMEOUT_S = 120


def _teardown_timeout() -> int:
    """Teardown timeout in seconds; a POSITIVE XP_TEARDOWN_TIMEOUT_S overrides."""
    return _subprocess_env._env_int(
        "XP_TEARDOWN_TIMEOUT_S", _DEFAULT_TEARDOWN_TIMEOUT_S
    )


def _declared_teardown(smm_dir: Path) -> str | None:
    """The project's declared worktree teardown command, or None.

    Absent-tolerant AND corrupt-tolerant — this diverges from
    `worktree_bootstrap._declared_bootstrap`, which lets a corrupt
    system_context propagate as a fail-closed gate read. Teardown is a
    cleanup action, not a gate: nothing downstream trusts its verdict, so a
    corrupt system_context degrades rather than raising.

    It degrades QUIET, not SILENT, and the difference is the whole point.
    Returning a bare None would make an unreadable context indistinguishable
    from the ordinary case of a project that declared no teardown — so the
    operator whose declared command silently stopped running would get no
    signal at all, and the containers would leak exactly as they did before
    this module existed. An absent declaration says nothing; an unreadable
    one says so.
    """
    try:
        doc = system_context_store.load_system_context(smm_dir)
    except (ValueError, OSError) as exc:
        print(
            f"worktree teardown skipped: system_context could not be read "
            f"({exc}). If this project declares a teardown command, it did "
            f"NOT run.",
            file=sys.stderr,
        )
        return None
    if doc is None:
        return None
    command = doc.get("stack", {}).get("worktree_teardown")
    return command or None


def run_teardown(wt_path: str, smm_dir: Path) -> None:
    """Run the project's declared teardown command IN the worktree being removed.

    Never raises. A missing declaration, a non-zero exit, a timeout, an
    OSError, and a corrupt system_context are all reported on stderr (with
    the child's captured output, when there is one) and swallowed — cleanup
    that refuses to clean up is worse than the leak it exists to prevent.
    This function does not validate `wt_path`; the caller owns confirming it
    points at a real worktree before invoking teardown.
    """
    command = _declared_teardown(smm_dir)
    if command is None:
        return

    timeout = _teardown_timeout()
    try:
        proc = _subprocess_env.run_in_new_process_group(
            command,
            cwd=wt_path,
            timeout=timeout,
            env=_subprocess_env.smm_child_env(smm_dir),
        )
    except subprocess.TimeoutExpired as exc:
        # The output the command managed to produce before it was killed is
        # usually the only clue to WHY it hung — "timed out after 120s" alone
        # sends the operator back to reproduce it by hand. run_in_new_process_group
        # drains the pipes after killing the group and re-raises carrying the
        # decoded text; getattr keeps this working if a plain TimeoutExpired
        # ever reaches here from another path.
        tail = (
            getattr(exc, "text_stderr", "") or getattr(exc, "text_stdout", "")
        ).strip()
        print(
            f"worktree teardown timed out after {timeout}s: {command}"
            + (f"\n{tail}" if tail else ""),
            file=sys.stderr,
        )
        return
    except OSError as exc:
        print(f"worktree teardown failed to start: {command}\n{exc}", file=sys.stderr)
        return

    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        print(
            f"worktree teardown failed (exit {proc.returncode}): {command}\n{output}",
            file=sys.stderr,
        )
