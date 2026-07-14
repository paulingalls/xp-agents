#!/usr/bin/env python3
"""Branch lifecycle operations for story and sprint branches.

Provides branch naming, creation, merge, and deletion for the
branching doctrine's stage-based workflow.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import execution_plan_store
import git_remote
import identity
import sprint_store

# Back-compat re-exports for code split out of this module: branch_lifecycle.py
# (merge/delete), branch_names.py (pure-string helpers; tests patch
# branch_names._utc_today_iso since the function lives there), and
# branch_resolution.py (SMM-state -> branch/stage answers).
#
# The privates are re-exported deliberately, not by accident: tests call
# branching._recorded_plan_branch directly and patch branching._git /
# branching.branch_exists. But a patch on THIS module only reaches callers that
# still live in THIS module — a call path that crosses into branch_resolution
# resolves the name in that module's globals. Patch where the caller lives.
from branch_lifecycle import (  # noqa: F401
    _fast_forward_if_safe,
    _merge_into_target,
    delete_branch,
    is_merged_into,
    merge_branch,
    survives_delete_of,
)
from branch_names import (  # noqa: F401
    _SPRINT_BRANCH_RE,
    _slugify,
    _utc_today_iso,
    branch_name,
    free_branch_name,
    is_free_branch,
    is_sprint_branch,
    plan_branch_name,
    scaffold_branch_name,
    sprint_branch_name,
)
from branch_resolution import (  # noqa: F401
    _DEFAULT_PRIMARY,
    _PROTECTED_BRANCHES,
    _git,
    _load_branching_strategy,
    _maybe_auto_promote,
    _recorded_plan_branch,
    _recorded_sprint_branch,
    branch_exists,
    get_branching_stage,
    get_merge_target,
    get_primary_branch,
    get_protected_branches,
    get_story_base_branch,
    get_story_base_branch_required,
    is_protected_branch,
    match_local_branches,
    ref_exists,
    resolve_sprint_branch_name,
    resolve_story_base,
    trusted_handed_base,
    trusted_story_base,
)


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


# Single source of truth: each create_*_branch enforces a min stage,
# and branching_cli._print_or_skip renders the same threshold in its
# skip message. Sharing the values here prevents the inner enforcement
# and the outer message from drifting if a stage threshold ever moves.
BRANCH_MIN_STAGE: dict[str, int] = {
    "story": 2,
    "sprint": 2,
    "plan": 2,
    "free": 2,
    "scaffold": 2,
}


def create_story_branch(
    cwd: str, story_id: str, slug: str, smm_dir: Path, *, base: str | None = None
) -> str | None:
    """Returns branch name or None if below story min stage.

    When base is provided, the story branch forks from that ref (for chaining
    dependent stories). When omitted, the story base is resolved from the
    sprint. Either way the value is VERIFIED before it reaches git — see
    ``trusted_story_base``, which raises rather than let an unresolvable or
    silently-degraded base become a fork point.

    The base=None arm is NOT dead code even though both SKILLs always pass
    --base: `branching.py create` without --base still reaches it (argparse
    defaults to None).
    """
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, story_id, slug)
    if get_branching_stage(smm_dir) >= BRANCH_MIN_STAGE["story"]:
        # Below the floor no branch is cut at all (_create_or_resume_branch
        # skips), so an unusable base is moot — and refusing one there would
        # break stage-0 inertness, where the plugin must not touch git.
        base = trusted_story_base(cwd, smm_dir, base)
    result = _create_or_resume_branch(
        cwd, name, smm_dir, min_stage=BRANCH_MIN_STAGE["story"], base=base
    )
    if result is not None and sprint_store.sprint_exists(smm_dir):
        try:
            sprint_store.set_story_branch(smm_dir, story_id, result)
        except ValueError:
            sys.stderr.write(
                f"WARN: story {story_id} not in sprint; "
                f"branch {result} created but not recorded\n"
            )
    return result


def create_sprint_branch(
    cwd: str, sprint_id: str, slug: str, smm_dir: Path
) -> str | None:
    """Returns sprint branch name or None if stage < 2.

    Forks off the recorded plan branch when execution_plan.branch is
    set and the branch exists locally; otherwise off current HEAD.

    Prefers the branch already RECORDED for this sprint_id over one rebuilt
    from `slug`. This is the second leg of the re-slice preserve, and without
    it the first leg is useless: /xp-sprint-start runs `create` and THEN
    `create-sprint --slug <goal-slug>`, so on a re-slice with a rewritten goal a
    slug-derived name would overwrite the branch _cmd_create just carried
    forward, cut a NEW empty branch, and orphan the real sprint branch —
    the preserve would survive a raw-CLI re-slice only. Same key as that
    preserve (sprint_id), so the two legs cannot disagree.

    Accepted consequence: after a goal rewrite the sprint branch KEEPS its
    original slug, and /xp-sprint-start's `resumed:` prompt becomes the only
    rename path — so it now fires on every re-slice. That is the trade: a stable
    branch beats a pretty name. A branch is an identity, not a label.

    Records the actual branch name into sprint.json on both create and
    resume paths so get_story_base_branch can look it up directly
    instead of reconstructing via slugify(goal). The re-record on resume is
    intentionally idempotent — it fixes any prior slug drift, which is only
    TRUE now that resume re-records what was recorded rather than what the
    current goal happens to slugify to.
    """
    name = resolve_sprint_branch_name(cwd, sprint_id, slug, smm_dir)
    base = _recorded_plan_branch(cwd, smm_dir)
    result = _create_or_resume_branch(
        cwd, name, smm_dir, min_stage=BRANCH_MIN_STAGE["sprint"], base=base
    )
    if result is not None:
        if sprint_store.sprint_exists(smm_dir):
            sprint_store.set_branch(smm_dir, result)
        _push_branch_if_remote(cwd, result)
    return result


def is_story_branch(branch: str) -> bool:
    """True if ``branch`` is a ``<user>/story-NNN[-slug]`` story branch."""
    return identity.extract_story_id(branch) is not None


def create_scaffold_branch(
    cwd: str,
    smm_dir: Path,
    *,
    current_branch: str | None = None,
) -> str | None:
    """Create or resume the surface-independent ``<user>/scaffold`` branch
    off the current branch.

    One shared scaffold branch per invocation: a multi-surface
    /xp-scaffold-acceptance loop calls this once per surface, and because
    the name carries no surface the second+ calls resume the same branch
    rather than chaining a per-surface branch off the first.

    Scaffold branches host the commit landed by /xp-scaffold-acceptance
    Step 8. Returns None below the plugin floor (stage < 2).
    Passes ``allow_dirty=True`` because the scaffold flow has already
    written files to disk before this call — the dirty state is the
    work being branched, not stale uncommitted changes.

    Base: the current branch, always — main→child off main, sprint /
    plan / free / generic feature→child off that branch. Branching off a
    protected base is fine (the scaffold child is what keeps the commit
    off the protected branch); forking off primary instead would strand
    user work that lives on the current branch.

    Guard: refuse (return None, create nothing) when the current branch
    is a story branch — a scaffold there would land inside the story's
    file_domain. The caller surfaces the user-facing guidance.

    ``current_branch`` is an optional caller-supplied override;
    ``commit_scaffold`` passes the value it already has so we don't
    re-shell-out to git. Lazy fallback keeps the public signature usable
    from contexts that don't have the cache.

    Pairs with ``commit_scaffold``'s ``CommitResult`` error contract:
    ``honest_errors=True`` returns ``None`` on git checkout/create failure
    instead of ``sys.exit(1)``, so the scaffold pipeline can fold the
    failure into ``CommitResult(ok=False, reason=...)`` rather than die.
    """
    user_ns = identity.user_namespace(cwd)
    name = scaffold_branch_name(user_ns)
    if current_branch is None:
        current_branch = identity.get_current_branch(cwd)
    if is_story_branch(current_branch):
        return None
    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=BRANCH_MIN_STAGE["scaffold"],
        base=current_branch,
        allow_dirty=True,
        honest_errors=True,
    )


def create_free_branch(
    cwd: str, slug: str, smm_dir: Path, *, base: str | None = None
) -> str | None:
    """Create or resume <user>/free-YYYY-MM-DD-<slug> off the merge target.

    Defaults to forking off ``get_merge_target`` — the recorded plan branch
    when one is active, else primary. The fork-base MUST match free-close's
    merge target: forking off primary while merging back into a plan branch
    drags primary-only commits (those landed since the plan branch forked)
    into the plan branch at close time. With no active plan, get_merge_target
    falls back to primary, so the common case is unchanged.

    An explicit ``base`` overrides that default — the escape hatch for free work
    that must fork off a specific ref (mirrors create_story_branch's ``base``).
    It is VERIFIED, not trusted: ``--base`` here is a human-typed ref, and on the
    resume arm a typo is silent (``_fast_forward_if_safe`` no-ops against a ref
    git cannot resolve, and the CLI still prints `resumed:`). Same guard as the
    story path, via the same ``trusted_handed_base``.

    Free branches are scratch work outside of plans/sprints. Date is UTC.
    Returns None below the plugin floor (stage < 2). Per BRANCH_LIFECYCLE
    design, free-branch protection activates at the floor to keep
    exploratory work off protected branches.
    """
    user_ns = identity.user_namespace(cwd)
    name = free_branch_name(user_ns, slug)
    if base is not None and get_branching_stage(smm_dir) >= BRANCH_MIN_STAGE["free"]:
        # Stage-gated for the same reason create_story_branch's is: below the
        # floor no branch is cut at all, so an unusable base is moot — and
        # refusing there would break stage-0 inertness.
        base = trusted_handed_base(cwd, base, omit_resolves="the merge target")
    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=BRANCH_MIN_STAGE["free"],
        base=base if base is not None else get_merge_target(smm_dir, cwd),
    )


def list_user_branches(cwd: str, prefix: str) -> list[str]:
    """Return branches matching <user-ns>/<prefix>-*, excluding HEAD."""
    user_ns = identity.user_namespace(cwd)
    current = identity.get_current_branch(cwd)
    pattern = f"{user_ns}/{prefix}-*"
    return [b for b in match_local_branches(cwd, pattern) if b != current]


def list_free_branches(cwd: str) -> list[str]:
    """Return free branches owned by the current user, excluding HEAD."""
    return list_user_branches(cwd, "free")


def create_plan_branch(cwd: str, slug: str, smm_dir: Path) -> str | None:
    """Create or resume <user>/plan-<slug> off the primary branch.

    Records the branch into execution_plan.json on BOTH create and
    resume paths so a regenerated plan still links to its branch and
    any prior slug drift is fixed idempotently. Mirrors the sprint
    primitive's atomic re-record. Returns None when stage < plan.
    """
    user_ns = identity.user_namespace(cwd)
    name = plan_branch_name(user_ns, slug)
    result = _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=BRANCH_MIN_STAGE["plan"],
        base=get_primary_branch(smm_dir),
    )
    if result is not None:
        if execution_plan_store.plan_exists(smm_dir):
            execution_plan_store.set_branch(smm_dir, result)
        _push_branch_if_remote(cwd, result)
    return result


def commits_ahead(cwd: str, base: str, head: str = "HEAD") -> int | None:
    """Count commits on ``head`` not reachable from ``base``.

    Thin wrapper over ``git rev-list --count <base>..<head>``. Returns None
    when git fails (bad base ref, not a repo) or the count is unparseable —
    callers treat None as "can't tell, don't suppress" so a gate keyed on
    this never silently skips a legitimate signal.
    """
    r = _git(["git", "rev-list", "--count", f"{base}..{head}"], cwd)
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def check_plan_divergence(cwd: str, smm_dir: Path, threshold: int = 10) -> dict | None:
    """Count how far the plan branch has fallen behind primary.

    Returns None if no plan branch is configured or resolvable.
    Returns a dict with commits_behind, plan_branch, primary.
    When commits_behind >= threshold, adds warning and suggestion
    (merge, not rebase — safer for shared branches).
    """
    plan_branch = _recorded_plan_branch(cwd, smm_dir)
    if not plan_branch:
        return None
    primary = get_primary_branch(smm_dir)
    behind = commits_ahead(cwd, base=plan_branch, head=primary)
    if behind is None:
        return None
    result: dict = {
        "commits_behind": behind,
        "plan_branch": plan_branch,
        "primary": primary,
    }
    if behind >= threshold:
        result["suggestion"] = f"git merge {primary}"
        result["warning"] = (
            f"Plan branch '{plan_branch}' is {behind} commits behind "
            f"'{primary}'. Consider merging {primary} into the plan branch."
        )
    return result


if __name__ == "__main__":
    import branching_cli

    sys.exit(branching_cli.main())
