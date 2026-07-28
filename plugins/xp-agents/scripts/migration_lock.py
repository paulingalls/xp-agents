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


def holder_state(target: str) -> bool | None:
    """Is the pid a lock names running? None when the target names no pid.

    Three answers, not two: an unverifiable target is not a corpse, and the
    callers treat it differently from one they proved dead.

    ASCII digits only, exactly what init.sh's `^[0-9]+$` accepts: the two sides
    must agree on what counts as a pid, or one waits for a holder the other
    clears. `str.isdigit` alone is wider — true for superscripts, which `int()`
    then rejects, making the guard itself the traceback.
    """
    if not (target.isascii() and target.isdigit()) or int(target) <= 0:
        return None
    try:
        os.kill(int(target), 0)
    except ProcessLookupError:
        return False
    except OverflowError:
        # Too big for a C int, so not a pid this tool can check — and NOT
        # "running": init.sh's `kill -0` rejects the same value and stops
        # waiting for it, so reporting a holder here would leave a lock no side
        # waits for and this command refuses to clear.
        return None
    except OSError:
        # EPERM: the process EXISTS and is simply not ours. Not proven dead, so
        # it reads as held.
        return True
    return True
