#!/usr/bin/env python3
"""Measure whether a declared command needs more than a bare checkout to pass.

Runs ONE project-declared command twice — in the primary checkout, and in a
throwaway worktree created bare at HEAD — and compares the two TRUE exit codes.
A divergence means the command depends on state `git worktree add` does not
materialize: installed dependencies, generated artifacts, local config. That is
the worktree bootstrap gap `worktree_bootstrap.run_bootstrap` exists to close.

WHY A DIFFERENTIAL AND NOT AN EXIT CODE. A measurement over two real repos
tried two plausible bootstrap candidates. BOTH exited 0; one installed 2208 packages,
looked perfect, and fixed neither failure. A candidate's own exit code proves
nothing, so the only thing that separates a working bootstrap from a plausible
one is re-running this measurement. The acceptance-scaffold's worktree step therefore
calls this TWICE: once to detect a gap, once to verify a candidate actually
closed it.

PER COMMAND, NEVER PER PROJECT. The same measurement found one repo whose TESTS
were checkout-invariant (an install closed the gap) while its TYPECHECK was
checkout-variant (no install could — the types are emitted by a dev server at
startup). A project cannot be classified once; each declared command takes its
own differential. The command is therefore an ARGUMENT here and is never read
from a field: the verify call differentials an unverified CANDIDATE, which
lives in no field yet.

THE RESULT IS A CANDIDATE SIGNAL, NEVER A VERDICT. Two false positives are
intrinsic and are reported with every result — see `CAVEATS`. The caller's job
is to absorb the over-firing by asking a human; the cost of that honesty is a
spurious question, never a false green.

Leaf module: imports DOWN only (`worktree`, `_subprocess_env`,
`shell_exit_structure`) and is deliberately NOT wired into `spawn_teammate`.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Same explicit-statement reasoning as `worktree_bootstrap`: these are
# scripts/-local siblings, and a bare import only resolves once scripts/ is on
# sys.path. A direct `python3 worktree_differential.py` must not depend on some
# other module having bootstrapped the path first. A statement is a barrier
# isort cannot hoist an import above.
sys.path.insert(0, str(Path(__file__).parent))

import _subprocess_env
import shell_exit_structure
import worktree

# The four outcomes. Callers branch on these, so they are named constants rather
# than inline strings: a typo in a branch is silent, a typo in a name is an
# AttributeError.
OUTCOME_GAP = "gap"
OUTCOME_NO_GAP = "no_gap"
OUTCOME_REFUSED = "refused"
OUTCOME_ERROR = "error"

# Two legs of a project command, sequentially. Generous by default because the
# differential costs ~2x the project's own command (measured: 55s + 57s for
# this repo's suite), and tunable for a project whose command is slower.
_DEFAULT_DIFFERENTIAL_TIMEOUT_S = 900

# Bounded so a chatty failing command cannot turn a machine-readable verdict
# into megabytes of log on the caller's stdout.
_OUTPUT_TAIL_CHARS = 4000

CAVEATS = (
    "PATH SENSITIVITY: a worktree always sits at a different, usually longer "
    "path than the primary, so any path-sensitive check diverges for reasons "
    "unrelated to gitignored state. A measured control repo failed this way "
    "with no provisioning gap at all.",
    "HEAD vs WORKING TREE: the worktree leg is created at HEAD, while the "
    "primary leg runs against the working tree, so any uncommitted tracked "
    "edit diverges the legs on its own.",
)


def _differential_timeout() -> int:
    """Per-leg timeout in seconds; a POSITIVE XP_DIFFERENTIAL_TIMEOUT_S wins.

    Never None. `run_in_new_process_group` hands this straight to
    `communicate()`, where None blocks forever — so a hung declared command
    would hang this tool, and the process-group kill that exists to reap its
    descendants would never fire.
    """
    return _subprocess_env._env_int(
        "XP_DIFFERENTIAL_TIMEOUT_S", _DEFAULT_DIFFERENTIAL_TIMEOUT_S
    )


def _throwaway_name() -> str:
    """A per-run worktree name that can never collide with a teammate's.

    `worktree.worktree_path` resolves into `{data}/{project-id}/worktrees/` —
    the SAME directory that holds live teammate worktrees with uncommitted work
    — and this module removes with `force=True`. A fixed name would eventually
    name a teammate's tree and `git worktree remove --force` would destroy it,
    so the name is unique per run AND deliberately outside the
    `worktree-story-*` shape teammates use.

    The `worktree-` prefix is kept so the existing sweepers (and an operator
    scanning that directory) recognise it as a worktree at all.
    """
    return f"worktree-diff-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def undifferentiable_reason(command: str) -> str | None:
    """Why *command* cannot be differentialed, or None if it can.

    A command whose own exit status does not reach the shell's reports someone
    else's number: `pytest | tee log` reports TEE's exit status, so its two
    legs would be compared on a value that says nothing about either checkout.
    Refusing loudly is the whole point — the measurement that motivated this
    module nearly reported its own red control run as green through exactly
    this shape.

    The check is `shell_exit_structure.exit_reaches_shell`, which is STRUCTURAL:
    a pipe, `;`, `||`, `&` or `$(...)` decides it, with no knowledge of what the
    command runs. `test_attribution.exit_status_proves_runner_passed` answers a
    neighbouring question and must NOT be substituted here — it is vacuously
    True for any command naming no recognized test-framework runner, so it
    clears `tsc --noEmit | tee log` and `cargo build | tee log`. The measured
    checkout-variant artifact was a TYPECHECK; reusing it would ship a gate
    that looks present and catches almost nothing.
    """
    if not command.strip():
        return "no command to differential: the command is empty"
    if not shell_exit_structure.exit_reaches_shell(command):
        return (
            f"cannot differential {command!r}: its own exit status does not "
            f"reach the shell's exit status — a pipe, ';', newline, '||', '&' "
            f"or a $(...) capture discards or captures it, so the two legs "
            f"would be compared on a number that means nothing. Declare a form "
            f"whose exit status survives (a leading 'cd x &&' or a trailing "
            f"'&& next' still counts)."
        )
    return None


def _tail(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _OUTPUT_TAIL_CHARS:
        return text
    return "..." + text[-_OUTPUT_TAIL_CHARS:]


def _remove_throwaway(name: str, cwd: str) -> bool:
    """Remove the throwaway worktree. True if the path is gone afterwards.

    `remove_worktree_dir`, NOT `remove_worktree`: the latter also deletes a
    branch, and on a detached HEAD the branch it would be handed is the literal
    worktree NAME. `force=True` is the documented post-work case — a throwaway
    that just ran a project command always holds build artifacts, so
    `force=False` would raise `WorktreeNotEmpty` essentially every run.

    The filesystem fallback is for a directory git does not KNOW is a worktree:
    a run killed between `mkdir` and `git worktree add` strands exactly that,
    and `git worktree remove` refuses it forever. Safe to `rmtree` only because
    the name is per-run unique and outside the teammate namespace — never a
    directory anyone else owns.

    Best-effort rather than raising, because this runs in a `finally`: an
    exception here would REPLACE whatever the measurement was already raising
    and destroy the diagnostic. A surviving path is reported on stderr instead,
    which is loud without being destructive.
    """
    worktree.remove_worktree_dir(name, cwd, force=True)
    wt = worktree.worktree_path(name, cwd)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=cwd, capture_output=True)
    if wt.exists():
        print(f"could not remove the throwaway worktree at {wt}", file=sys.stderr)
        return False
    return True


def _add_detached_worktree(name: str, cwd: str) -> Path:
    """Create a BARE worktree at HEAD and return its path.

    `--detach` so no branch is created, and therefore none has to be deleted —
    which also sidesteps the branch-ownership decision tree a named worktree
    drags in. Every other `git worktree add` in this repo creates a branch.

    Placement is `worktree.worktree_path`, which puts the tree OUT of the repo.
    That is load-bearing, not tidiness: an in-repo worktree resolves
    dependencies by walking UP into the primary's tree, which silently HIDES
    the very gap being measured.

    A pre-existing path is cleared rather than fatal. The name is unique per
    run, so a path that already exists is debris a crashed earlier run stranded
    between `add` and its `finally`; failing on it would make the tool
    un-runnable until someone cleaned up by hand.
    """
    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists() and not _remove_throwaway(name, cwd):
        raise RuntimeError(f"could not clear a stranded throwaway worktree at {wt}")
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not create the throwaway worktree at {wt}: "
            f"{result.stderr.strip() or 'non-zero exit'}"
        )
    return wt


def differential(
    command: str, cwd: str, smm_dir: Path, timeout: int | None = None
) -> dict:
    """Run *command* in *cwd* and in a bare worktree, and compare exit codes.

    *cwd* is the PRIMARY CHECKOUT ROOT: the worktree leg runs at the throwaway's
    root, so a *cwd* pointing into a subdirectory would compare two different
    relative positions as well as two checkouts.

    Both legs go through `_subprocess_env.run_in_new_process_group` with one
    shared env and one shared timeout. The shared env is not incidental —
    `smm_child_env` resolves SMM_DIR to an absolute path, and without it the
    legs would differ by their ENVIRONMENT as well as their checkout, measuring
    the wrong variable.

    The exit codes are the command's own. The shared runner reads `returncode`
    off the child directly, with no shell pipeline between it and Python; that
    is what makes capturing output pipe-safe. Building a pipeline here would
    bring the hazard straight back, which is why the precondition above refuses
    a command that already contains one.

    Returns a dict whose `outcome` is one of four values, and never raises for
    a measurement failure:

      * `gap`     — the exit codes differ. The worktree needs state a bare
                    checkout does not have. A CANDIDATE SIGNAL: see `caveats`.
      * `no_gap`  — the exit codes are identical, whatever they are. A command
                    that fails IDENTICALLY in both checkouts has no gap; it has
                    a bug, which is not this instrument's question.
      * `refused` — the command is not differentiable at all.
      * `error`   — a leg timed out. A timeout has NO returncode to compare, so
                    it cannot be a gap: reporting one would demand a bootstrap
                    for a merely slow command, and no bootstrap could fix it.
                    Refuse over guess.

    A timeout is caught and reported; anything else (a broken git, an
    unwritable worktree root) propagates, because it means the tool itself is
    broken rather than the measurement being inconclusive. Either way the
    throwaway is removed in a `finally`.
    """
    reason = undifferentiable_reason(command)
    if reason is not None:
        return _result(OUTCOME_REFUSED, command, reason=reason)

    seconds = timeout if timeout and timeout > 0 else _differential_timeout()
    env = _subprocess_env.smm_child_env(smm_dir)
    name = _throwaway_name()
    wt = _add_detached_worktree(name, cwd)
    try:
        primary = _subprocess_env.run_in_new_process_group(
            command, cwd=cwd, timeout=seconds, env=env
        )
        throwaway = _subprocess_env.run_in_new_process_group(
            command, cwd=str(wt), timeout=seconds, env=env
        )
    except subprocess.TimeoutExpired as exc:
        return _result(
            OUTCOME_ERROR,
            command,
            reason=(
                f"a leg timed out after {seconds}s, so there is no exit code to "
                f"compare: {command}. Tune XP_DIFFERENTIAL_TIMEOUT_S if this "
                f"command legitimately needs longer."
            ),
            worktree_output=_tail(
                getattr(exc, "text_stdout", "") or getattr(exc, "text_stderr", "")
            ),
        )
    finally:
        # The guarantee this module owns: nothing else in shipped code wraps
        # worktree create/remove in try/finally. See _remove_throwaway for the
        # force/fallback reasoning.
        _remove_throwaway(name, cwd)

    same = primary.returncode == throwaway.returncode
    outcome = OUTCOME_NO_GAP if same else OUTCOME_GAP
    return _result(
        outcome,
        command,
        primary_exit=primary.returncode,
        worktree_exit=throwaway.returncode,
        worktree_output=_tail(throwaway.stderr or throwaway.stdout or ""),
    )


def _result(
    outcome: str,
    command: str,
    *,
    reason: str = "",
    primary_exit: int | None = None,
    worktree_exit: int | None = None,
    worktree_output: str = "",
) -> dict:
    """One shape for all four outcomes, so a consumer can read a field without
    first branching on the outcome. `caveats` rides on every result: they are
    intrinsic to the method, not to any particular verdict."""
    return {
        "outcome": outcome,
        "command": command,
        "primary_exit": primary_exit,
        "worktree_exit": worktree_exit,
        "reason": reason,
        "worktree_output": worktree_output,
        "caveats": list(CAVEATS),
    }


def main() -> None:
    """JSON on stdout, exit 0 whenever the tool RAN.

    The verdict lives in the JSON and is deliberately NOT encoded in the exit
    code: a non-zero "gap found" would be indistinguishable from "the tool
    itself failed", which is precisely the conflation this instrument exists to
    expose.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--command", required=True, help="the command to differential")
    parser.add_argument("--cwd", default=".", help="the primary checkout root")
    parser.add_argument("--smm-dir", required=True, help="the SMM directory")
    parser.add_argument("--timeout", type=int, default=None, help="per-leg seconds")
    args = parser.parse_args()

    result = differential(
        args.command, args.cwd, Path(args.smm_dir), timeout=args.timeout
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
