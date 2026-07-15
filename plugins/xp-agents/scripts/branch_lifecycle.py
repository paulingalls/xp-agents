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

import re
import subprocess
import sys
import time
from collections.abc import Callable

# git's own words when another process holds the repo's index. Matched on the
# SIGNATURE rather than the exit code, because git returns the same 128 for plenty
# of failures that will never resolve themselves.
_INDEX_LOCK_RE = re.compile(r"index\.lock", re.IGNORECASE)

_LOCK_RETRY_ATTEMPTS = 3
_LOCK_RETRY_BASE_S = 0.2

# A network push is slower than a local git op, so this is well above the `_git`
# 10s cap. It exists only to bound an unreachable/stalled origin so the close
# cannot hang forever; a timeout warns and the merge proceeds (never aborts).
_PUSH_TIMEOUT_S = 30


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def _git_retry_on_lock(
    args: list[str],
    cwd: str,
    *,
    attempts: int = _LOCK_RETRY_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> subprocess.CompletedProcess:
    """Run a git command, retrying ONLY a transient `.git/index.lock` collision.

    A sibling worktree (or a teammate's git process) can hold the index for a
    moment. That is what bit story-005: the close's merge failed on the lock, and
    the pipeline carried on and marked the story done unmerged.

    NOT a blanket retry, deliberately. A merge conflict will not resolve itself on
    the second attempt, and retrying it would turn a clear error into a slow,
    confusing one — so only the lock signature comes back for another go. Safe to
    retry because git takes the lock BEFORE it mutates anything: a lock-failed
    command is a clean no-op, not a half-applied one.

    Bounded, with a growing backoff. The holder may never let go, and an unbounded
    spin would HANG the close rather than fail it; on exhaustion the caller gets
    git's own stderr, which is what makes `_merge_into_target` exit non-zero.

    HONEST FRAMING: this narrows the window, it does not close it. The mark-done
    gate (`story_done_gate`) is the actual fix — it refuses to record a story as
    shipped when the merge did not land, however the merge came to fail. This just
    keeps the common case from ever reaching it.

    `sleep` is injected so the tests can assert the retry STRUCTURALLY — that it
    tried again and backed off — without buying a slow, flaky wall-clock test.
    """
    result = _git(args, cwd)
    for attempt in range(1, attempts):
        if result.returncode == 0 or not _INDEX_LOCK_RE.search(result.stderr or ""):
            return result
        sleep(_LOCK_RETRY_BASE_S * (2 ** (attempt - 1)))
        result = _git(args, cwd)
    return result


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
    # Both legs go through the lock retry: the checkout takes the index too, so a
    # sibling worktree's git process can lose us the close just as easily there as
    # at the merge itself.
    r = _git_retry_on_lock(["git", "checkout", target], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {target}: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    r = _git_retry_on_lock(
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


def push_source_no_verify(cwd: str, source: str) -> None:
    """Re-push `source` to origin before a close merge; warn — never abort.

    Close-time fixes (the quality-review validate-and-fix and any "fix now" at
    the findings step) land on `source` AFTER the close's initial Step-2 push,
    so the PR record — and anything reading the remote head — is stale relative
    to what the merge is about to ship. Re-push `source` so the PR reflects the
    merged ref.

    `--no-verify` is deliberate and is NOT skipping verification. At story-close
    cmd_merge runs from the ORCHESTRATOR checkout (on the sprint base) while
    `source` is the teammate's STORY branch, so a pre-push hook would test the
    WRONG tree: it proves nothing, costs minutes, and FAILS on a red base,
    leaving the PR stale in exactly the case this exists to fix. The identical
    commits already passed a verified pre-push at Step 2 and are verified again
    seconds later by cmd_merge's TARGET push (right tree). What is skipped is a
    redundant wrong-tree run.

    Warn-don't-abort: the merge is the truth; a stale PR is a record problem,
    not a correctness one. A close-time amend/rebase can make this re-push
    non-fast-forward — it then warns and the PR stays stale, which is
    acceptable. A generous timeout (longer than this module's `_git` 10s cap,
    since a network push is slower than a local git op) bounds the wait so an
    unreachable/stalled origin cannot HANG the whole close forever — and the
    TimeoutExpired is caught into the SAME warn-don't-abort path as the OSError
    and returncode cases, so a timeout still never raises and never aborts.
    """
    try:
        r = subprocess.run(
            ["git", "push", "--no-verify", "origin", source],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_PUSH_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Honor "never abort" for the spawn-failure and timeout paths too, not
        # just the returncode path below. An unreachable origin (timeout) or a
        # spawn failure (OSError/FileNotFoundError) would otherwise abort
        # cmd_merge BEFORE the merge. Warn and let the merge proceed.
        sys.stderr.write(
            f"warn: could not run git to re-push {source} before merge; the PR "
            f"record may be stale relative to what merged (the merge is the "
            f"truth and proceeds). {exc}\n"
        )
        return
    if r.returncode != 0:
        sys.stderr.write(
            f"warn: failed to re-push {source} before merge; the PR record may "
            f"be stale relative to what merged (the merge is the truth and "
            f"proceeds). git said: {r.stderr.strip()}\n"
        )


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
    """Delete a branch, and never one whose work is not already somewhere else.

    NEVER TRUST ``git branch -d`` TO BE THE MERGE PROOF. Git's rule is "fully merged
    in its UPSTREAM branch, or in HEAD if no upstream was set" — and upstream WINS
    when one exists. Every story branch has one by the time it is deleted:
    /xp-story-close Step 2 runs ``git push -u origin <branch>``. So on any repo with
    a remote, `-d` exits 0 on a branch that was merely PUSHED and never merged into
    its base, printing a warning nobody reads. Verified empirically, not inferred.

    That is why the ancestry check runs FIRST here, against ``merge_target`` (or HEAD,
    which is what `-d` is universally believed to check). It is not defence in depth:
    ``story_done_gate`` reads branch ABSENCE as git-enforced proof that the merge
    landed, so a `-d` that deletes an unmerged branch lets a story whose merge FAILED
    be marked done — the exact bug that gate exists to stop.

    ``-d`` still runs after the check, for the guards it alone has (refusing to
    delete the branch you are standing on, say). It legitimately refuses when a
    branch's tip differs from its upstream tracking ref even though it is fully
    merged to the target — the case worktree teammates hit every close — so with a
    ``merge_target`` we fall back to ``-D``, but only once ``survives_delete_of``
    proves the target is a ref that OUTLIVES the delete (the ancestry test alone says
    "safe" about a target that IS the branch). Without ``merge_target`` the legacy
    contract holds: False on -d refusal, no force-delete attempted.
    """
    if not is_merged_into(cwd, name, merge_target or "HEAD"):
        return False
    if _git(["git", "branch", "-d", name], cwd).returncode == 0:
        return True
    if merge_target and survives_delete_of(cwd, name, merge_target):
        return _git(["git", "branch", "-D", name], cwd).returncode == 0
    return False
