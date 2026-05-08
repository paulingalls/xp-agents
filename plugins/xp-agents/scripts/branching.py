#!/usr/bin/env python3
"""Branch lifecycle operations for story and sprint branches.

Provides branch naming, creation, merge, and deletion for the
branching doctrine's stage-based workflow.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
import execution_plan_store
import git_remote
import identity
import sprint_store
import system_context_store


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def _is_merged_into(cwd: str, branch: str, target: str) -> bool:
    """True iff ``branch`` is reachable from ``target``."""
    r = _git(["git", "merge-base", "--is-ancestor", branch, target], cwd)
    return r.returncode == 0


def branch_name(user_ns: str, id_: str, slug: str) -> str:
    return f"{user_ns}/{id_}-{_slugify(slug)}"


def sprint_branch_name(user_ns: str, sprint_id: str, slug: str) -> str:
    return branch_name(user_ns, sprint_id, slug)


def plan_branch_name(user_ns: str, slug: str) -> str:
    return f"{user_ns}/plan-{_slugify(slug)}"


def free_branch_name(user_ns: str, slug: str) -> str:
    return f"{user_ns}/free-{_utc_today_iso()}-{_slugify(slug)}"


_SPRINT_BRANCH_RE = re.compile(r"^[^/]+/sprint-\d{3}-[a-z0-9-]+$")


def is_sprint_branch(name: str) -> bool:
    return bool(_SPRINT_BRANCH_RE.match(name))


_DEFAULT_PRIMARY = "main"


def _load_branching_strategy(smm_dir: Path) -> dict:
    """Read system_context.branching_strategy or {} on any failure."""
    path = smm_dir / "system_context.json"
    if not path.exists() or path.is_symlink():
        return {}
    try:
        ctx = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return ctx.get("branching_strategy") or {}


def _maybe_auto_promote(smm_dir: Path, current: int) -> int:
    """Auto-promote Stage 1 -> Stage 2 (plugin floor). Idempotent.

    Mutates system_context.json's branching_strategy.stage in place
    and emits a one-time decision event. Returns 2 on success; on an
    OSError (read-only SMM, missing dir, lock contention) returns the
    original stage so the next call to get_branching_stage retries the
    promotion. Schema-validation ValueErrors are intentionally NOT
    caught — they signal corrupt input or a code bug and propagate.
    """
    if current != 1:
        return current
    try:
        ctx = system_context_store.load_system_context(smm_dir)
        if ctx is None:
            return current
        ctx.setdefault("branching_strategy", {})["stage"] = 2
        system_context_store.save_system_context(smm_dir, ctx)
        event = _common.make_event(
            "decision",
            "branching",
            "Auto-promoted branching stage 1 -> 2 (plugin floor)",
            topic="branching-stage-auto-promote",
            metadata={"action": "stage_auto_promote", "from_stage": 1, "to_stage": 2},
        )
        _common.append_safe(smm_dir, event)
        return 2
    except OSError as e:
        # Filesystem failure (read-only SMM, missing dir, lock contention).
        # Fail-soft: log and return original stage so the next call retries.
        # Schema-validation ValueError is intentionally NOT caught — it
        # signals a corrupt input or a code bug, both of which deserve to
        # crash loud rather than silently mask the contract.
        _common.log_hook_error(
            f"branching auto-promote failed: {e}",
            error_class=type(e).__name__,
            from_stage=1,
            to_stage=2,
        )
        return current


def get_branching_stage(smm_dir: Path) -> int:
    """Return the branching stage. NOT side-effect free.

    A stage=1 read triggers a one-time auto-promotion (file mutation
    + decision event) via `_maybe_auto_promote`. Read-only or locked
    SMMs fail soft and return 1 unpromoted; the next call retries.
    Stage 0/2/3 reads remain pure.
    """
    stage = _load_branching_strategy(smm_dir).get("stage", 0)
    return _maybe_auto_promote(smm_dir, stage)


def match_local_branches(cwd: str, pattern: str) -> list[str]:
    """Run git for-each-ref against `refs/heads/<pattern>` and return short names."""
    r = _git(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/{pattern}"],
        cwd,
    )
    if r.returncode != 0:
        return []
    return [b for b in r.stdout.splitlines() if b]


def _recorded_plan_branch(cwd: str, smm_dir: Path) -> str | None:
    """Return execution_plan.branch when set AND a matching local branch exists.

    Prefers exact match. Falls back to a `<branch>-*` suffix-prefix scan
    (anchored on a separator so `plan-feat-*` doesn't match
    `plan-featured`) and prints a stderr note when the fallback fires —
    drift discovery should be visible. Note: get_story_base_branch
    handles sprint slug drift by reconstructing via slugify(goal); plan
    branches glob-scan because the recorded value IS the branch name.
    """
    plan = execution_plan_store.load_plan(smm_dir)
    if plan is None:
        return None
    plan_branch = plan.get("branch")
    if not plan_branch:
        return None
    if branch_exists(cwd, plan_branch):
        return plan_branch
    matches = sorted(match_local_branches(cwd, f"{plan_branch}-*"))
    if not matches:
        return None
    drifted = matches[0]
    print(
        f"note: recorded plan branch '{plan_branch}' not found locally;"
        f" using prefix match '{drifted}'",
        file=sys.stderr,
    )
    return drifted


def get_merge_target(smm_dir: Path, cwd: str) -> str:
    """Return the branch to merge into.

    Plan branch when execution_plan.branch resolves locally (exact match
    preferred, `<branch>-*` prefix-fallback for slug drift); otherwise
    the primary integration branch.
    """
    return _recorded_plan_branch(cwd, smm_dir) or get_primary_branch(smm_dir)


def get_primary_branch(smm_dir: Path) -> str:
    """Return the repo's primary integration branch.

    Stage 0-2: always 'main'. Stage 3 reads system_context's
    branching_strategy.integration_branch, defaulting to 'main' when
    missing or null.

    Routes through ``get_branching_stage`` so reads of the primary
    branch also fire the Stage 1 -> 2 auto-promote side-effect — single
    chokepoint guarantees stage progression regardless of entry path.
    """
    if get_branching_stage(smm_dir) < 3:
        return _DEFAULT_PRIMARY
    bs = _load_branching_strategy(smm_dir)
    return bs.get("integration_branch") or _DEFAULT_PRIMARY


_PROTECTED_BRANCHES = {"main", "master"}


def is_protected_branch(stage: int, branch: str) -> bool:
    return stage >= 1 and branch in _PROTECTED_BRANCHES


def is_worktree_clean(cwd: str) -> bool:
    r = _git(["git", "status", "--porcelain"], cwd)
    return r.returncode == 0 and r.stdout.strip() == ""


def branch_exists(cwd: str, name: str) -> bool:
    r = _git(["git", "rev-parse", "--verify", f"refs/heads/{name}"], cwd)
    return r.returncode == 0


def _try_checkout(cwd: str, branch: str) -> bool:
    """Attempt to check out ``branch``. Return True on success, False on failure.

    On failure, the git stderr is forwarded to the caller's stderr so the user
    sees the same diagnostic ``_checkout_or_exit`` previously printed before
    its sys.exit. Callers decide whether to escalate to sys.exit (legacy
    story/sprint/free helpers) or surface the failure as a structured ``None``
    return (scaffold helper, which feeds ``commit_scaffold``'s
    ``CommitResult(ok=False, reason=...)`` contract).
    """
    r = _git(["git", "checkout", branch], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {branch}: {r.stderr}", file=sys.stderr)
        return False
    return True


def _checkout_or_exit(cwd: str, branch: str) -> None:
    if not _try_checkout(cwd, branch):
        sys.exit(1)


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

    Returns the branch name, or None when the configured branching
    stage is below `min_stage`. The base argument forks the new branch
    from a specific ref instead of HEAD; on resume, the existing branch
    fast-forwards to `base` when its tip is an ancestor of `base` so
    sprint-start scaffolds don't snap to a stale base mid-sprint.
    Branches with unique commits ahead of base are left alone.

    ``allow_dirty=True`` skips the worktree-clean precondition for cases
    where the dirty state IS the work being branched (e.g., scaffold-
    acceptance has just written files and now needs to land them on a
    fresh branch). git checkout -b preserves uncommitted changes when
    the new branch starts at the same commit.

    ``honest_errors=True`` surfaces checkout/create failures as ``None``
    instead of ``sys.exit(1)``, so callers wrapping this in a structured
    error contract (scaffold-acceptance's ``CommitResult``) can map the
    failure to ``ok=False`` rather than have the process die mid-pipeline.
    Worktree-dirty failures still ``sys.exit`` — the user must clean up
    before retrying. Stage gating still returns ``None`` regardless.
    """
    if get_branching_stage(smm_dir) < min_stage:
        return None

    if branch_exists(cwd, name):
        if honest_errors:
            if not _try_checkout(cwd, name):
                return None
        else:
            _checkout_or_exit(cwd, name)
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

    # Push freshly-created branch only — resumed branches may have
    # diverged from remote and would fail-noisy every kickoff. Push
    # failure is non-fatal: branch exists locally, retry hint below
    # covers recovery (don't add a second error message).
    if not git_remote.push_branch(cwd, name):
        print(f"  retry: git push -u origin {name}", file=sys.stderr)

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

    When base is provided, the story branch forks from that ref (for
    chaining dependent stories). When omitted, uses the resolved story
    base (sprint branch at stage 2+, otherwise primary).
    """
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, story_id, slug)
    if base is None:
        base = get_story_base_branch(smm_dir, cwd)
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

    Records the actual branch name into sprint.json on both create and
    resume paths so get_story_base_branch can look it up directly
    instead of reconstructing via slugify(goal). The re-record on
    resume is intentionally idempotent — it fixes any prior slug drift.
    """
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, sprint_id, slug)
    base = _recorded_plan_branch(cwd, smm_dir)
    result = _create_or_resume_branch(
        cwd, name, smm_dir, min_stage=BRANCH_MIN_STAGE["sprint"], base=base
    )
    if result is not None and sprint_store.sprint_exists(smm_dir):
        sprint_store.set_branch(smm_dir, result)
    return result


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def create_scaffold_branch(cwd: str, surface: str, smm_dir: Path) -> str | None:
    """Create or resume ``<user>/scaffold-<surface>`` off the primary branch.

    Scaffold branches host the commit landed by /xp-scaffold-acceptance
    Step 8. Returns None below the plugin floor (stage < 2).
    Passes ``allow_dirty=True`` because the scaffold flow has already
    written files to disk before this call — the dirty state is the
    work being branched, not stale uncommitted changes.

    Pairs with ``commit_scaffold``'s ``CommitResult`` error contract:
    ``honest_errors=True`` returns ``None`` on git checkout/create failure
    instead of ``sys.exit(1)``, so the scaffold pipeline can fold the
    failure into ``CommitResult(ok=False, reason=...)`` rather than die.
    """
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, "scaffold", surface)
    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=BRANCH_MIN_STAGE["scaffold"],
        base=get_primary_branch(smm_dir),
        allow_dirty=True,
        honest_errors=True,
    )


def create_free_branch(cwd: str, slug: str, smm_dir: Path) -> str | None:
    """Create or resume <user>/free-YYYY-MM-DD-<slug> off the primary branch.

    Free branches are scratch work outside of plans/sprints. Date is UTC.
    Returns None below the plugin floor (stage < 2). Per BRANCH_LIFECYCLE
    design, free-branch protection activates at the floor to keep
    exploratory work off protected branches.
    """
    user_ns = identity.user_namespace(cwd)
    name = free_branch_name(user_ns, slug)
    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=BRANCH_MIN_STAGE["free"],
        base=get_primary_branch(smm_dir),
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
    if result is not None and execution_plan_store.plan_exists(smm_dir):
        execution_plan_store.set_branch(smm_dir, result)
    return result


def get_story_base_branch(smm_dir: Path, cwd: str) -> str:
    """Return the base branch for stories: sprint branch at stage 2+, else primary.

    Prefers sprint['branch_name'] (recorded atomically at create time) and
    falls back to slugify(goal) reconstruction so older sprints written
    before atomic recording still resolve.
    """
    primary = get_primary_branch(smm_dir)
    stage = get_branching_stage(smm_dir)
    if stage < 2:
        return primary

    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return primary

    stored = sprint.get("branch_name")
    if stored and branch_exists(cwd, stored):
        return stored

    user_ns = identity.user_namespace(cwd)
    name = sprint_branch_name(user_ns, sprint["sprint_id"], sprint["goal"])

    if branch_exists(cwd, name):
        return name

    return primary


def _merge_into_target(cwd: str, source_branch: str, target: str) -> None:
    _checkout_or_exit(cwd, target)
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
    r = _git(["git", "rev-list", "--count", f"{plan_branch}..{primary}"], cwd)
    if r.returncode != 0:
        return None
    behind = int(r.stdout.strip())
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
