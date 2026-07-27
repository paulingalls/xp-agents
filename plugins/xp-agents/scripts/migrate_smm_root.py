#!/usr/bin/env python3
"""Inspect, and when asked relocate, an SMM still sitting on a host-managed root.

A session relocates the SMM by itself on first resolution after upgrade. It
declines while a teammate looks live, and that decline is not always temporary:
the signal is a worktree DIRECTORY existing, cleanup refuses to remove one whose
branch never merged, so a single abandoned story pins the SMM in the directory
`claude plugin uninstall` deletes. Only a human can tell an abandoned worktree
from a running teammate, which is what this tool is for.

RELOCATION is still not implemented here. Copying, the whole-tree re-sync and
the forward pointer live in `init.sh`, the one boundary every reader and writer
passes through; the tool only reports state and drives init.sh through
`XP_SMM_MIGRATE`.

Lock CLEARING is the exception, and it lives here on purpose: a resolver must
never remove a lock it did not create. Breaking one is a read then a delete, no
shell primitive makes that pair indivisible, and an automatic breaker therefore
ran N-at-a-time at every session start. Moving it here does NOT make two holders
impossible — taking the name aside frees it, so a racer can claim it in the gap
and the no-clobber restore then fails. What changes is that the outcome stays
recoverable and loud (nothing is deleted, and the tool says so and exits
non-zero), and that the exposure is one deliberate human invocation instead of
every hook. That residual is the "second set of race conditions" this docstring
used to predict; see `clear_stale_lock`.

Reporting resolves through init.sh with relocation suppressed, so it never moves
anything. It is not a pure read: resolution seeds any missing default files, the
same way opening a session does. Nothing about WHERE the SMM lives changes.

    migrate_smm_root.py                  # report; relocates nothing
    migrate_smm_root.py --confirm        # clear a DEAD lock, then relocate
    migrate_smm_root.py --confirm --force  # relocate anyway (read the report first)
"""

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import smm_dir_resolve

_INIT_SH = Path(__file__).parent.parent / "smm" / "init.sh"
_IN_PLACE_GLOB = ".in-place-active-*"

# The lock contract, pinned here because two files now have to agree on it:
# init.sh claims this name BESIDE the project's `smm/` directory, and the claim
# is a SYMLINK whose target is the holder's pid (`ln -s "$$"` in init.sh's
# migrate_legacy_smm) — one syscall publishes the name and the holder together,
# so a lock is never observable without its holder. Anything else at that name is
# residue from an older version of init.sh by construction.
_LOCK_NAME = ".migrate.lock"


def _run_init(mode: str | None) -> Path | None:
    """Resolve via init.sh under a relocation mode. None on any failure."""
    env = dict(os.environ)
    if mode:
        env["XP_SMM_MIGRATE"] = mode
    else:
        env.pop("XP_SMM_MIGRATE", None)
    try:
        result = subprocess.run(
            ["bash", str(_INIT_SH)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"init.sh could not be run: {exc}", file=sys.stderr)
        return None
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or f"exit {result.returncode}"
        print(f"init.sh failed: {detail}", file=sys.stderr)
        return None
    return Path(result.stdout.strip())


# Relocation bookkeeping, not SMM content: the forward pointer is written into
# the SOURCE after a successful copy, so counting it would make every verified
# relocation report a one-file mismatch. Matched at the TOP LEVEL only —
# init.sh writes it exactly there, and excluding the basename anywhere in the
# tree would silently drop a same-named file a future SMM layout might carry.
_BOOKKEEPING = {".migrated-to"}


def _tree_stats(root: Path) -> tuple[int, int]:
    """(file count, total bytes) for the SMM content under ``root``."""
    files = 0
    total = 0
    for path in root.rglob("*"):
        if path.parent == root and path.name in _BOOKKEEPING:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        files += 1
        with contextlib.suppress(OSError):
            total += path.stat().st_size
    return files, total


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def live_signals(smm_dir: Path) -> list[str]:
    """Everything init.sh would read as a live teammate, named for a human.

    Mirrors init.sh's `teammates_are_live`: worktree directories beside the SMM,
    and in-place markers inside it. Reporting only — the gate itself stays in
    one place.
    """
    signals: list[str] = []
    worktrees = smm_dir.parent / "worktrees"
    if worktrees.is_dir():
        signals.extend(f"worktrees/{p.name}" for p in sorted(worktrees.iterdir()))
    signals.extend(p.name for p in sorted(smm_dir.glob(_IN_PLACE_GLOB)))
    return signals


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
    """
    if not target.isdigit() or int(target) <= 0:
        return None
    try:
        os.kill(int(target), 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError):
        # EPERM (the process exists but is not ours) and an unusable pid both
        # mean "not proven dead", which must read as held.
        return True
    return True


def _report_lock(lock: Path) -> None:
    """Name the lock and its holder — nothing else makes a dead one visible.

    No resolver removes a lock any more, so a crashed relocation's lock blocks
    every session's automatic attempt until a human looks. This is where they
    look.
    """
    if not lock.is_symlink() and not lock.exists():
        return
    print(f"  lock:        {lock}")
    if not lock.is_symlink():
        print("  lock holder: none — not a symlink, so residue from an older version")
        return
    target = os.readlink(lock)
    match holder_state(target):
        case None:
            print(f"  lock holder: {target!r} — names no pid, liveness unverifiable")
        case True:
            print(f"  lock holder: pid {target} — RUNNING, a migration may be underway")
        case False:
            print(f"  lock holder: pid {target} — not running; --confirm clears it")


def _preserve_taken(lock: Path, taken: Path, held: str) -> int:
    """Refuse, leaving what was taken where a human can put it back.

    Deleting here is the entire defect this replaces: what we hold may be a
    claim a LIVE process made in the gap between the readlink and the rename,
    and its owner is already copying. So nothing is removed, and the message
    says plainly that two migrations may be in flight.
    """
    print(
        f"Refusing to clear {lock}: it was taken aside and could not be put "
        "back, because another claim now occupies the name.",
        file=sys.stderr,
    )
    print(f"  taken aside: {taken} (holds {held})", file=sys.stderr)
    print(
        "TWO MIGRATIONS MAY NOW BE IN FLIGHT — the claim above and whatever "
        "holds the lock name. Nothing was deleted. Let both finish, check the "
        "SMM, then remove the file above by hand.",
        file=sys.stderr,
    )
    return 1


def clear_stale_lock(lock: Path) -> int:
    """Clear a migration lock whose holder is gone. 0 means the name is free.

    Take-then-inspect, never read-then-delete. `os.rename` is an atomic
    single-winner take, so of N callers exactly one ends up holding what was at
    that name and there is no second delete left to land on somebody's live
    claim. The readlink is still a SEPARATE syscall from the rename, so what was
    taken is not necessarily what was verified — hence the inspection after.

    This does NOT make two holders impossible. Taking the name aside FREES it,
    and a racer can claim it in that gap; the no-clobber restore then fails and
    two processes believe they hold the lock. That outcome is left RECOVERABLE
    instead of papered over — see `_preserve_taken`. There is deliberately no
    atexit, no try/finally and no trap that removes the taken file: a cleanup
    trap on exactly this path is what made the automatic breaker delete live
    claims.
    """
    if not lock.is_symlink() and not lock.exists():
        return 0

    was_symlink = lock.is_symlink()
    try:
        expected = os.readlink(lock) if was_symlink else None
    except OSError:
        # Gone between the two syscalls — another invocation of this command
        # cleared it. The name is free, which is all the caller asked about.
        return 0
    if expected is not None and holder_state(expected):
        print(
            f"Refusing to clear {lock}: its holder (pid {expected}) is running, "
            "so a migration may be underway. --force overrides the "
            "teammate-liveness signal, never lock ownership.",
            file=sys.stderr,
        )
        return 1

    taken = lock.with_name(f"{lock.name}.clearing.{os.getpid()}")
    try:
        os.rename(lock, taken)
    except OSError as exc:
        print(
            f"Refusing to clear {lock}: could not take it aside ({exc}). "
            "Something else got to the name first.",
            file=sys.stderr,
        )
        return 1

    if taken.is_symlink():
        actual = os.readlink(taken)
        if was_symlink and actual == expected:
            os.unlink(taken)
            if holder_state(actual) is None:
                held = f"it named no pid this tool can check ({actual!r})"
            else:
                held = f"its holder (pid {actual}) was gone"
            print(f"Cleared the migration lock {lock}: {held}.")
            return 0
        # Not what was verified — a claim landed in the gap. Put it back:
        # os.symlink refuses an occupied name, so a newer claim wins over the
        # restore and one is never clobbered.
        try:
            os.symlink(actual, lock)
        except OSError:
            return _preserve_taken(lock, taken, f"pid {actual}")
        os.unlink(taken)
        print(
            f"Refusing to clear {lock}: a claim naming pid {actual} appeared "
            "while it was being cleared. It has been put back.",
            file=sys.stderr,
        )
        return 1

    if was_symlink:
        # A symlink was recorded and something else was taken. Restoring it
        # would mean clobbering whatever is at the name now, so preserve it.
        return _preserve_taken(lock, taken, "no holder this tool can read")

    # A non-symlink is residue by construction (see _LOCK_NAME). Nothing removes
    # one automatically any more, which makes it the one shape that would block
    # relocation forever — clearing it deliberately is what this command is for.
    if taken.is_dir():
        contents = ", ".join(sorted(p.name for p in taken.iterdir())) or "nothing"
        shutil.rmtree(taken)
        print(
            f"Cleared the migration lock {lock}: a directory containing "
            f"{contents} — residue from an older version."
        )
    else:
        os.unlink(taken)
        print(
            f"Cleared the migration lock {lock}: a plain file — residue from an "
            "older version."
        )
    return 0


def _report(current: Path, at_risk: bool, signals: list[str], lock: Path) -> None:
    files, size = _tree_stats(current)
    print("SMM relocation")
    print(f"  current:     {current}")
    print(f"  destination: {destination_for(current)}")
    print(f"  contents:    {files} files, {_human(size)}")
    _report_lock(lock)
    if at_risk:
        print(
            "  at risk:     YES — this root is deleted by "
            "'claude plugin uninstall' (--keep-data opts out)"
        )
    else:
        print("  at risk:     no — this root is not managed by the plugin host")
    # Only when a relocation is actually wanted. Signals hold back a relocation;
    # a safe root has none pending, so listing them there told the user to clear
    # a directory so "the next session relocates on its own" and then finished
    # with "Nothing to do."
    if signals and at_risk:
        print()
        # Worded for both modes: `run` decides whether these block or are being
        # overridden, and says which. Claiming "blocked" here and then
        # relocating under --force would make the report contradict the run.
        print(f"{len(signals)} live-teammate signal(s), which hold relocation back:")
        for signal in signals:
            print(f"  {signal}")
        print()
        print("If those belong to a running teammate, leave them alone — relocating")
        print("out from under one splits the event log with no merge path. If they")
        print("are leftovers from an abandoned story, clear them and the next")
        print("session relocates on its own, or pass --confirm --force.")


def _warn_stranded_worktrees(source: Path, signals: list[str]) -> None:
    """Name the worktrees a forced relocation just cut loose from the tooling.

    Only the `smm/` directory is copied; the sibling `worktrees/` tree stays
    where it was. That is invisible in normal use because relocation declines
    while any worktree exists — but --force overrides exactly that, and
    `worktree.worktree_path()` derives placement from the SMM's parent, so after
    the move the tooling looks for those worktrees under the NEW root and finds
    nothing. Cleanup then fails on a branch name it cannot resolve, and the real
    directories sit in the root `claude plugin uninstall` deletes. Loud beats
    discovering it at cleanup time.
    """
    stranded = [s for s in signals if s.startswith("worktrees/")]
    if not stranded:
        return
    print(
        f"WARNING: {len(stranded)} worktree director(ies) did NOT move and are no "
        "longer where the tooling looks for them, so /xp-story-close cannot "
        "clean them up:",
        file=sys.stderr,
    )
    for name in stranded:
        print(f"  {source.parent / name}", file=sys.stderr)
    print(
        "They are still under the root 'claude plugin uninstall' deletes. Merge "
        "or archive their branches and remove them by hand ('git worktree "
        "remove <path>', then 'git worktree prune').",
        file=sys.stderr,
    )


def _verify(source: Path, dest: Path) -> bool:
    """Compare the two trees after a relocation. Loud, never silent."""
    src_files, src_size = _tree_stats(source)
    dst_files, dst_size = _tree_stats(dest)
    if (src_files, src_size) == (dst_files, dst_size):
        print(f"Verified: {dst_files} files, {_human(dst_size)} at the new location.")
        return True
    print(
        "WARNING: the copy does not match the source "
        f"(source {src_files} files/{_human(src_size)}, "
        f"destination {dst_files} files/{_human(dst_size)}).",
        file=sys.stderr,
    )
    print(
        "The source was NOT deleted — inspect both before removing anything.",
        file=sys.stderr,
    )
    return False


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report on, or relocate, an SMM on a host-managed data root."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually relocate; without it this only reports",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "relocate even when a teammate looks live (implies --confirm); it "
            "does NOT clear a lock whose holder is still running"
        ),
    )
    args = parser.parse_args(argv)
    confirm = args.confirm or args.force

    pinned = os.environ.get("SMM_DIR", "").strip()
    if pinned:
        print(
            f"SMM_DIR is set to {pinned}, which short-circuits resolution. "
            "Unset it to inspect or relocate this project's derived SMM.",
            file=sys.stderr,
        )
        return 2

    current = _run_init("off")
    if current is None:
        return 2

    at_risk = smm_dir_resolve.is_under_plugin_managed_root(current)
    signals = live_signals(current)
    lock = lock_path_for(current)
    _report(current, at_risk, signals, lock)

    if not at_risk:
        print()
        print("Nothing to do.")
        return 0
    if not confirm:
        print()
        print("Dry run — nothing was relocated. Re-run with --confirm to move it.")
        return 0
    if signals and not args.force:
        print()
        print(
            "Refusing to relocate while a teammate looks live. "
            "Re-run with --force once you are sure.",
            file=sys.stderr,
        )
        return 1

    print()
    if signals:
        print(f"--force: relocating despite {len(signals)} live-teammate signal(s).")
    source = current
    mode = "force" if args.force else None
    # A crashed relocation's lock blocks every session's automatic attempt and
    # nothing removes it on its own any more, so clearing it is the reason this
    # command exists. It refuses on a live holder regardless of --force.
    cleared = clear_stale_lock(lock)
    if cleared != 0:
        return cleared
    moved = _run_init(mode)
    if moved is None:
        return 2
    if moved == source:
        print("Relocation did not happen; the SMM is still at the old location.")
        return 1
    print(f"Relocated to {moved}")
    ok = _verify(source, moved)
    print(f"The old copy is still at {source} — delete it once you are satisfied.")
    _warn_stranded_worktrees(source, signals)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
