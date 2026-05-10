#!/usr/bin/env python3
"""Lifecycle primitives for branch merge and deletion.

Closed call island extracted from branching.py to keep that module
under the 500-line target. branching.py re-exports every symbol here
for backwards compat — callers should keep importing from branching.

Cross-call graph (no outbound calls beyond this module):
- _fast_forward_if_safe -> _is_merged_into
- delete_branch         -> _is_merged_into
- merge_branch          -> _merge_into_target
"""

import subprocess
import sys


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def _is_merged_into(cwd: str, branch: str, target: str) -> bool:
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
    if not _is_merged_into(cwd, branch, base):
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


def delete_branch(cwd: str, name: str, *, merge_target: str | None = None) -> bool:
    """Delete a branch; try ``-d`` first, fall back to ``-D`` only when proven safe.

    ``git branch -d`` refuses when a branch's tip differs from its
    upstream tracking ref, even if it is fully merged to the
    integration target — the case worktree teammates hit every close.
    When ``merge_target`` is provided AND ``-d`` refuses, fall back to
    ``-D`` iff the branch is provably an ancestor of ``merge_target``.
    Without ``merge_target`` the legacy contract holds: False on -d
    refusal, no force-delete attempted.
    """
    if _git(["git", "branch", "-d", name], cwd).returncode == 0:
        return True
    if merge_target and _is_merged_into(cwd, name, merge_target):
        return _git(["git", "branch", "-D", name], cwd).returncode == 0
    return False
