#!/usr/bin/env python3
"""Provision a freshly created teammate worktree via a project-declared command.

`git worktree add` materializes only tracked files, so everything gitignored —
installed dependencies, generated artifacts, local config — is missing from a
fresh worktree. A project declares `stack.worktree_bootstrap` in its
system_context; spawn_teammate.create_worktree calls run_bootstrap here before
the teammate takes its first turn.

Leaf module: imports DOWN (system_context_store only) and knows nothing about
spawning. spawn_teammate re-exports `run_bootstrap` by identity so existing
callers and their patch targets keep working.
"""

import subprocess
import sys
from pathlib import Path

# Make smm/ importable, the same way scripts/_common.py does. An explicit
# statement rather than the side-effect `import worktree  # isort: split` trick
# spawn_teammate uses: a bare import is reorderable, and isort WILL hoist the
# smm import above it (ruff --fix did exactly that), leaving this module
# importable only when something else happened to bootstrap sys.path first. A
# statement is a barrier isort cannot cross, so the ordering can't silently rot.
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import system_context_store

# Same explicit-statement reasoning as the smm/ insert above, applied to this
# module's own directory: _subprocess_env is a scripts/-local sibling, and a
# bare `import _subprocess_env` only resolves once scripts/ is on sys.path.
# Callers that reached this module via worktree.py's side-effect import
# already added it, but a direct `python3 worktree_bootstrap.py` or an
# import order that skips worktree.py must not depend on that accident.
sys.path.insert(0, str(Path(__file__).parent))

import _subprocess_env

# Bootstrap can be a cold dependency install, not the 6.4s warm-cache
# re-run that was measured — generous by default, tunable per project.
_DEFAULT_BOOTSTRAP_TIMEOUT_S = 600


def _bootstrap_timeout() -> int:
    """Bootstrap timeout in seconds; a POSITIVE XP_BOOTSTRAP_TIMEOUT_S overrides.

    Only positive, and that is not input-hygiene fussiness: `timeout=0` makes
    subprocess.run raise TimeoutExpired before the command has run at all, so a
    healthy project's every spawn would die with "timed out after 0s" and leave
    an unprovisioned worktree — the false-green run_bootstrap exists to prevent,
    arriving as a knob. Zero and negatives express no runnable budget, so they
    are not an override; they fall back to the default, exactly as unparseable
    text does.

    Delegates to _subprocess_env._env_int, shared with
    verify_acceptance._cmd_timeout — kept as a named wrapper (not inlined at
    the call site) because tests patch/call this name directly.
    """
    return _subprocess_env._env_int(
        "XP_BOOTSTRAP_TIMEOUT_S", _DEFAULT_BOOTSTRAP_TIMEOUT_S
    )


def _declared_bootstrap(smm_dir: Path) -> str | None:
    """The project's declared worktree bootstrap command, or None.

    Absent-tolerant, corrupt-intolerant: no system_context, or one that
    declares no command, means "most projects" and returns None. A corrupt
    system_context raises ValueError out of load_system_context, and that
    propagates — per the Constraints pillar, a gate read fails CLOSED rather
    than silently skipping the provisioning step it was supposed to gate.
    """
    doc = system_context_store.load_system_context(smm_dir)
    if doc is None:
        return None
    command = doc.get("stack", {}).get("worktree_bootstrap")
    return command or None


def run_bootstrap(wt_path: str, smm_dir: Path) -> None:
    """Run the project's declared bootstrap command IN the new worktree.

    `git worktree add` materializes only tracked files, so everything
    gitignored — installed dependencies, generated artifacts, local config —
    is missing from a fresh worktree. Measured on a real bun/Expo monorepo,
    that absence produces two distinct failure modes: the DOMINANT mode is a
    loud false-RED — a typecheck run hits TS2882 "Cannot find module or type
    declarations", exit 2, and a bare test run exits 1 over a dozen
    unresolvable modules, stranding a weak teammate who never finishes. A
    second, contrived mode is a false-GREEN: missing generated types can make
    a type augmentation permissive so broken code compiles clean — though in
    practice the false-RED fires first and masks it. Provisioning is
    therefore a correctness step, not an ergonomic one.

    The command is OPAQUE to us, and deliberately so. Gitignored state splits
    into checkout-invariant (installable, shareable) and checkout-variant
    (generated per checkout, or derived from the checkout's own path — copying
    it across checkouts is silently wrong). Only the project knows which of
    its state is which, so the project declares a command that encodes the
    split, and we never inspect or reimplement what it does. This is what
    keeps the mechanism agnostic to the project's language.

    Fails LOUD and leaves the worktree standing. A half-provisioned worktree
    must never host an agent — the false-green above is exactly what a
    half-provisioned one produces. The worktree is deliberately NOT rolled
    back: bootstrap has by then written files, so removal would need
    force=True and would destroy the evidence needed to diagnose the failure.
    /xp-assign already instructs the operator to delete a partial worktree
    before re-spawning.
    """
    command = _declared_bootstrap(smm_dir)
    if command is None:
        return

    timeout = _bootstrap_timeout()
    try:
        # shell=True: a project-declared shell string (install pipelines,
        # `&&` chains, redirects), authored by the project in its own
        # system_context — trusted local state, the same trust boundary
        # verify_acceptance's declared AC commands sit behind, not external
        # input. cwd is the new worktree: provisioning it is the entire point,
        # and inheriting the process cwd would provision the main checkout
        # instead. SMM_DIR is resolved because a relative value would
        # otherwise resolve against that new cwd.
        proc = subprocess.run(
            command,
            shell=True,  # noqa: secret
            cwd=wt_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_subprocess_env.smm_child_env(smm_dir),
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            f"worktree bootstrap timed out after {timeout}s: "
            f"{command}\nWorktree left at {wt_path} for inspection. "
            f"Tune XP_BOOTSTRAP_TIMEOUT_S if this project legitimately needs "
            f"longer."
        ) from exc

    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(
            f"worktree bootstrap failed (exit "
            f"{proc.returncode}): {command}\n{output}\n"
            f"Worktree left at {wt_path} for inspection — delete it "
            f"before retrying."
        )
