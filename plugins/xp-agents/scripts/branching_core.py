#!/usr/bin/env python3
"""Low-level branch primitives shared by branching.py.

Split out of branching.py to keep that module under the file-size cap.
These are the small git-shelling building blocks (existence checks,
checkout, create-or-resume) that the higher-level create_*_branch
wrappers in branching.py compose. Imports flow DOWNWARD only — this
module must never import from branching.py, or the two would form a
circular import.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import git_remote
import sprint_store
from branch_lifecycle import _fast_forward_if_safe
from branch_resolution import _git, _verified_local, branch_exists, get_branching_stage


def _push_branch_if_remote(cwd: str, name: str) -> None:
    """Best-effort `git push -u origin <name>` when a remote exists.

    Used by the sprint/plan create wrappers so the first child merge has a
    remote ref to PR against (decision sprint-plan-push-at-create). Best-
    effort: the branch already exists locally, so a push failure must not
    fail creation — relay stderr and move on. No-op without a remote (the
    common test/offline case).

    Pushes with ``--no-verify``: a freshly-created branch holds no commits
    beyond its base, so a project pre-push hook (e.g. an integration test
    suite) has nothing new to gate. Skipping it avoids a pointless multi-
    second run. Raw network latency can still exceed _git's timeout, so the
    TimeoutExpired is caught here too — either way the branch is local and
    reaches origin at close time as a fallback.
    """
    if not git_remote.has_remote(cwd):
        return
    try:
        r = _git(["git", "push", "--no-verify", "-u", "origin", name], cwd)
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"WARN: push of {name} at create timed out; reaches origin at close\n"
        )
        return
    if r.returncode != 0:
        sys.stderr.write(f"WARN: failed to push {name} at create: {r.stderr}")


def is_worktree_clean(cwd: str) -> bool:
    r = _git(["git", "status", "--porcelain"], cwd)
    return r.returncode == 0 and r.stdout.strip() == ""


def is_git_worktree(cwd: str) -> bool:
    """True when *cwd* is inside a real, checkable git working tree.

    Distinguishes a genuinely dirty tree from a path that can't be
    status-checked at all — a missing directory (subprocess raises) or a
    non-repo path (git exits non-zero). Callers that skip work on an
    unresolvable target use this to avoid conflating an errored ``git status``
    with a dirty tree.
    """
    try:
        r = _git(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    except (OSError, subprocess.SubprocessError):
        # Missing dir (OSError) or a hung/errored git (TimeoutExpired et al.,
        # since _git runs with a timeout) — an uncheckable target, not a dirty
        # one. Fail to "not a worktree" so callers skip rather than crash.
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _try_checkout(cwd: str, branch: str) -> bool:
    """Check out ``branch``; return True on success, False (with stderr) on failure.

    Bool return lets callers escalate (sys.exit for legacy story/sprint/free
    helpers) or surface the failure as ``None`` (scaffold's CommitResult).
    """
    r = _git(["git", "checkout", branch], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {branch}: {r.stderr}", file=sys.stderr)
        return False
    return True


def _create_or_resume_branch(
    cwd: str,
    name: str,
    smm_dir: Path,
    min_stage: int,
    *,
    base: str | None = None,
    allow_dirty: bool = False,
    honest_errors: bool = False,
) -> str | None:
    """Create `name` or resume it if it already exists locally.

    Returns None when stage < min_stage. ``base`` forks new branches
    from that ref and fast-forwards resumed branches whose tip is an
    ancestor of ``base`` (branches with unique commits are left alone),
    so sprint-start scaffolds don't snap to a stale base mid-sprint.

    ``allow_dirty=True`` skips the worktree-clean precondition — needed
    by scaffold-acceptance, which has already written the files this
    branch will host. ``honest_errors=True`` returns ``None`` on git
    checkout/create failure instead of ``sys.exit(1)`` so scaffold's
    ``CommitResult`` contract can map it to ``ok=False`` rather than
    die mid-pipeline. Worktree-dirty failures still ``sys.exit``.
    """
    if get_branching_stage(smm_dir) < min_stage:
        return None

    if branch_exists(cwd, name):
        if not _try_checkout(cwd, name):
            if honest_errors:
                return None
            sys.exit(1)
        if base is not None:
            _fast_forward_if_safe(cwd, name, base)
        return name

    if not allow_dirty and not is_worktree_clean(cwd):
        print("Working tree is dirty — commit or stash changes first", file=sys.stderr)
        sys.exit(1)

    cmd = ["git", "checkout", "-b", name]
    if base is not None:
        cmd.append(base)
    r = _git(cmd, cwd)
    if r.returncode != 0:
        print(f"Failed to create branch {name}: {r.stderr}", file=sys.stderr)
        if honest_errors:
            return None
        sys.exit(1)

    # No push at create here — a fresh branch has no commits beyond its base,
    # so for the frequent story/free/scaffold wrappers the branch reaches
    # origin at close time (close_common.py), not here. The infrequent
    # sprint/plan wrappers are the exception: they call _push_branch_if_remote
    # after this returns, so the first child merge has a remote PR base
    # (decision sprint-plan-push-at-create).
    return name


def _recorded_story_branch(cwd: str, smm_dir: Path, story_id: str) -> str | None:
    """The branch already recorded for THIS story_id, if it still exists locally.

    Mirrors ``_recorded_sprint_branch`` (branch_resolution.py) — the story-branch
    leg of the same reslice-preserve. Without this,
    create_story_branch always rebuilt the name from the caller's slug, and
    /xp-schedule + /xp-assign always pass a TITLE-derived slug (SKILL.md's
    ``--slug <title-slug>``): a reslice that RETITLES a scheduled/ready story
    would cut a second, empty branch from the new slug and strand the branch
    already carried forward as an orphan.

    ``sprint_store.get_story_branch_name`` returns the raw recorded value with
    no existence check of its own, so it is verified via the shared
    ``_verified_local`` (the same helper ``_recorded_sprint_branch`` calls) —
    a recorded-but-vanished branch is stale, and the slug-built name is the
    better guess. Sharing the helper keeps the two reslice-preserve legs from
    diverging if the verification rule ever changes.
    """
    return _verified_local(cwd, sprint_store.get_story_branch_name(smm_dir, story_id))
