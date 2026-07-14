#!/usr/bin/env python3
"""Lifecycle primitives for branch merge and deletion.

Closed call island extracted from branching.py to keep that module
under the 500-line target. branching.py re-exports every symbol here
for backwards compat — callers should keep importing from branching.

Cross-call graph (no outbound calls beyond this module):
- _fast_forward_if_safe -> is_merged_into
- delete_branch         -> survives_delete_of, is_merged_into
- merge_branch          -> _merge_into_target
"""

import subprocess
import sys


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def is_merged_into(cwd: str, branch: str, target: str) -> bool:
    """True iff ``branch`` is reachable from ``target``."""
    r = _git(["git", "merge-base", "--is-ancestor", branch, target], cwd)
    return r.returncode == 0


def _fast_forward_if_safe(cwd: str, branch: str, base: str) -> None:
    """Fast-forward `branch` to `base` when `branch` is an ancestor of `base`.

    No-op when `branch` has unique commits or has diverged — silent
    rebase could lose work. The branch must already be checked out.
    Logs a stderr note on a successful fast-forward so the user knows
    the ref moved under them.
    """
    if not is_merged_into(cwd, branch, base):
        return
    old_sha = _git(["git", "rev-parse", branch], cwd).stdout.strip()
    new_sha = _git(["git", "rev-parse", base], cwd).stdout.strip()
    if old_sha == new_sha:
        return
    ff = _git(["git", "merge", "--ff-only", base], cwd)
    if ff.returncode != 0:
        print(
            f"note: fast-forward of {branch} to {base} failed: {ff.stderr.strip()}",
            file=sys.stderr,
        )
        return
    print(
        f"note: fast-forwarded {branch} to {base} ({old_sha[:7]}..{new_sha[:7]})",
        file=sys.stderr,
    )


def _merge_into_target(cwd: str, source_branch: str, target: str) -> None:
    r = _git(["git", "checkout", target], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {target}: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    r = _git(
        ["git", "merge", "--no-ff", source_branch, "-m", f"Merge {source_branch}"],
        cwd,
    )
    if r.returncode != 0:
        details = (r.stderr or "") + (r.stdout or "")
        print(
            f"Merge of {source_branch} into {target} failed: {details.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)


def merge_branch(cwd: str, branch: str, target: str) -> None:
    _merge_into_target(cwd, branch, target)


def survives_delete_of(cwd: str, name: str, target: str) -> bool:
    """True iff ``target`` is a ref OTHER than ``name`` — one that still holds
    the branch's commits after ``refs/heads/<name>`` is gone.

    The other half of the ``-D`` safety proof, and the half that is easy to
    miss. "The branch is an ancestor of the target, so every commit on it is
    reachable from the target" is only worth something when the target is a
    DIFFERENT ref that OUTLIVES the delete. Two inputs make it vacuous:

    - ``target`` IS the branch. ``git merge-base --is-ancestor X X`` exits 0 —
      a commit is its own ancestor — so the ancestry test says "safe" about the
      one ref that is about to be destroyed. Reachable from the CLI's DEFAULT
      target: ``get_merge_target`` returns the recorded plan branch when one
      exists, so deleting THAT branch proves it against itself.
    - ``target`` is a bare SHA. Ancestry holds, but a SHA is not a ref; once the
      branch ref is gone nothing points at the work.

    Both answer False, which drops the caller back to the plain ``-d`` refusal —
    loud, non-destructive, and honest about what we could not prove. A target
    that names nothing answers False for the same reason.

    ``--verify --quiet`` is load-bearing: plain ``rev-parse --symbolic-full-name
    <junk>`` ECHOES its argument on stdout, so a nonexistent target would come
    back as a "ref" that happens not to equal the branch. With --verify it exits
    1 with empty stdout, and a bare SHA exits 0 with empty stdout — both fall
    out as False through the same emptiness check.
    """
    full = _git(
        ["git", "rev-parse", "--symbolic-full-name", "--verify", "--quiet", target],
        cwd,
    ).stdout.strip()
    return bool(full) and full != f"refs/heads/{name}"


def delete_branch(cwd: str, name: str, *, merge_target: str | None = None) -> bool:
    """Delete a branch; try ``-d`` first, fall back to ``-D`` only when proven safe.

    ``git branch -d`` refuses when a branch's tip differs from its
    upstream tracking ref, even if it is fully merged to the
    integration target — the case worktree teammates hit every close.
    When ``merge_target`` is provided AND ``-d`` refuses, fall back to
    ``-D`` iff the branch is provably an ancestor of ``merge_target`` AND
    ``merge_target`` is a ref that survives the delete (see
    ``survives_delete_of`` — the ancestry test alone says "safe" about a target
    that IS the branch). Without ``merge_target`` the legacy contract holds:
    False on -d refusal, no force-delete attempted.
    """
    if _git(["git", "branch", "-d", name], cwd).returncode == 0:
        return True
    if (
        merge_target
        and survives_delete_of(cwd, name, merge_target)
        and is_merged_into(cwd, name, merge_target)
    ):
        return _git(["git", "branch", "-D", name], cwd).returncode == 0
    return False
