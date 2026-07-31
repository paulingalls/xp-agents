#!/usr/bin/env python3
"""The migration lock: where it lives, and whether its holder is alive.

Moved out of ``migrate_smm_root.py`` so a SessionStart hook can read a lock's
state without importing a 492-line human-supervised CLI tool. Re-exported from
``migrate_smm_root`` BY IDENTITY (``from migration_lock import destination_for,
holder_state, lock_path_for``) so every existing ``tool.holder_state`` /
``tool.lock_path_for`` reference — and every ``mock.patch`` site targeting it —
resolves unchanged.
"""

import os
from pathlib import Path
from typing import Literal

# The lock contract, pinned here because two files now have to agree on it:
# init.sh claims this name BESIDE the project's `smm/` directory, and the claim
# is a SYMLINK whose target is the holder's pid (`ln -s "$$"` in init.sh's
# migrate_legacy_smm) — one syscall publishes the name and the holder together,
# so a lock is never observable without its holder. Anything else at that name is
# residue from an older version of init.sh by construction.
_LOCK_NAME = ".migrate.lock"


def destination_for(current: Path) -> Path:
    """Where relocation would put the SMM, given where it is now.

    The project id is the SMM's parent directory name — derived from the git
    common dir and identical under every root, so it survives the move.
    """
    base = os.environ.get("XP_AGENTS_DATA", "").strip()
    root = Path(base) if base else Path.home() / ".xp-agents" / "data"
    return root / current.parent.name / "smm"


def lock_path_for(current: Path) -> Path:
    """The migration lock init.sh would claim to relocate out of ``current``."""
    return destination_for(current).parent / _LOCK_NAME


PidCondition = Literal["alive", "dead", "exists_not_ours", "unknown"]


def probe_pid_condition(pid: int) -> PidCondition:
    """What `os.kill(pid, 0)` says about a pid — the CONDITION, not a verdict.

    The one liveness probe in the tree. Two call sites share it (`holder_state`
    below, and `in_place_marker._probe_pid`) and they answer the SAME condition
    differently, which is why this returns four states rather than the tri-state
    either site uses:

      * `exists_not_ours` (EPERM) is *held* to the lock and *unadjudicable* to
        the marker. A shared tri-state would have to fold it onto `unknown`
        alongside `OverflowError`, and the lock could then no longer read it as
        held — a behaviour change inside a lock.
      * `unknown` covers everything os.kill cannot answer: a value too big for a
        C int, and a non-positive pid.

    `pid <= 0` is `unknown`, NEVER `dead`. `os.kill(0, 0)` signals our OWN
    process group and SUCCEEDS; a negative pid targets a group. Neither is a pid
    we wrote, so both are corruption — not alive, but not proof of death either.
    Calling them dead would let the marker site delete a marker it cannot prove
    dead, which is the failure its tri-state exists to prevent.

    Total: never raises. `OverflowError` is an `ArithmeticError`, so it escapes
    an `OSError` clause and would otherwise crash the Stop hook that reaches
    here through the marker — and a crashed gate never fires at all.

    POSIX-only: `os.kill(pid, 0)` is a liveness probe here, but on Windows it
    would terminate the target. The plugin is already POSIX (flock, bash
    preloads), so this is a note, not a branch.
    """
    if pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead"
    except OverflowError:
        return "unknown"
    except OSError:
        # EPERM: the process EXISTS and is simply not ours.
        return "exists_not_ours"
    return "alive"


def holder_state(target: str) -> bool | None:
    """Is the pid a lock names running? None when the target names no pid.

    Three answers, not two: an unverifiable target is not a corpse, and the
    callers treat it differently from one they proved dead.

    ASCII digits only, exactly what init.sh's `^[0-9]+$` accepts: the two sides
    must agree on what counts as a pid, or one waits for a holder the other
    clears. `str.isdigit` alone is wider — true for superscripts, which `int()`
    then rejects, making the guard itself the traceback.

    One value the two sides classify differently, and it changes nothing: `0`
    passes init.sh's regex and `kill -0 0` SUCCEEDS there, because it signals
    the caller's own process group rather than a process — so init.sh reads "not
    verifiably dead" while this returns None ("no pid"). Both outcomes lead to
    the same place: init.sh never breaks a lock it did not create, so it waits
    and answers the legacy tree, and the advisory built on None tells the user
    to clear it by hand. Agreement on the VERDICT is what the invariant needs;
    a lock naming pid 0 is corrupt residue either way.

    The STRING contract stays here rather than moving into the shared probe: the
    agreement with init.sh's regex is what this call site needs, and the probe
    takes an int.
    """
    if not (target.isascii() and target.isdigit()):
        return None
    match probe_pid_condition(int(target)):
        case "alive":
            return True
        case "dead":
            return False
        case "exists_not_ours":
            # Not proven dead, so it reads as held.
            return True
        case "unknown":
            # A non-positive target, or one too big for a C int — not a pid this
            # tool can check, and NOT "running": init.sh's `kill -0` rejects the
            # same value and stops waiting for it, so reporting a holder here
            # would leave a lock no side waits for and this command refuses to
            # clear.
            return None


LockState = Literal["free", "stalled", "in-progress", "blocked", "unprobeable"]


def lock_state(smm_dir: Path) -> LockState:
    """The lock guarding relocation out of ``smm_dir``, named for its REMEDY.

    Total: never raises, because it runs on every session start and a
    traceback here costs the user the whole SessionStart payload, not just the
    advisory. Three things a hook process cannot rely on, all written for a
    human-run CLI where they could not happen:

    * ``destination_for`` calls ``Path.home()``, which raises ``RuntimeError``
      with no resolvable home.
    * ``os.readlink`` raises on a lock that vanishes after ``is_symlink``
      already answered.
    * ``Path.is_symlink`` and ``Path.exists`` themselves PROPAGATE EACCES on
      every interpreter before 3.14 (``lstat`` + an ignore list of
      ENOENT/ENOTDIR/EBADF/ELOOP), so an unsearchable destination directory —
      one sudo'd run leaving it root-owned is enough — raises out of what
      reads like a total predicate. Only 3.14's rewrite onto
      ``os.path.islink`` swallows it, which is why a suite that passes on the
      newest interpreter proves nothing here.

    A failed probe is its OWN state, ``unprobeable``, not ``free``. ``free``
    now carries a claim — "it relocates itself automatically" — and that claim
    is FALSE whenever the probe failed: one ``sudo claude`` run leaving the
    destination root-owned with a crashed relocation's lock in it raises
    EACCES here, and init.sh never breaks a lock on its own, so relocation is
    blocked indefinitely while the advisory says to wait it out. A state that
    cannot be established must not borrow the wording of one that was. The
    ONE exception is a lock that vanished between ``is_symlink`` and
    ``readlink``: gone IS free, and that race resolves in the safe direction.

    ``Literal``, not ``str``: five magic strings feeding the ``match/case``
    below with no exhaustiveness check is how a sixth state or a typo becomes
    a silently-missed branch.

    ``in-progress`` (a holder proved RUNNING) is the only state that must not
    suggest ``--confirm`` — guessing at a live holder is the automatic-breaker
    mistake this module exists to avoid. ``blocked`` covers both shapes that
    never self-release on their own (an unverifiable holder, and non-symlink
    residue) because they share the same remedy: the supervised report, then
    ``--confirm``. Only a holder proved dead (``stalled``) names ``--confirm``
    directly.
    """
    try:
        lock = lock_path_for(smm_dir)
        if not lock.is_symlink():
            return "blocked" if lock.exists() else "free"
        target = os.readlink(lock)
    except FileNotFoundError:
        # The lock was released between the two syscalls. Gone is free.
        return "free"
    except (RuntimeError, OSError):
        return "unprobeable"
    match holder_state(target):
        case None:
            return "blocked"
        case True:
            return "in-progress"
        case False:
            return "stalled"
