#!/usr/bin/env python3
"""Branch lifecycle operations for story and sprint branches.

Provides branch naming, creation, merge, and deletion for the
branching doctrine's stage-based workflow.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import execution_plan_store
import identity
import sprint_store


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def branch_name(user_ns: str, id_: str, slug: str) -> str:
    return f"{user_ns}/{id_}-{_slugify(slug)}"


def sprint_branch_name(user_ns: str, sprint_id: str, slug: str) -> str:
    return branch_name(user_ns, sprint_id, slug)


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


def get_branching_stage(smm_dir: Path) -> int:
    return _load_branching_strategy(smm_dir).get("stage", 0)


def _match_local_branches(cwd: str, pattern: str) -> list[str]:
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
    matches = sorted(_match_local_branches(cwd, f"{plan_branch}-*"))
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
    """
    bs = _load_branching_strategy(smm_dir)
    if bs.get("stage", 0) < 3:
        return _DEFAULT_PRIMARY
    return bs.get("integration_branch") or _DEFAULT_PRIMARY


_PROTECTED_BRANCHES = {"main", "master"}


def is_protected_branch(stage: int, branch: str) -> bool:
    return stage >= 1 and branch in _PROTECTED_BRANCHES


_HEREDOC_MSG_RE = re.compile(
    r"-m\s+\"\$\(cat\s+<<'?\w+'?\n(.*?)\n\w+\n\)\"",
    re.DOTALL,
)
_SIMPLE_MSG_RE = re.compile(
    r"""-m\s+(?:"((?:[^"\\]|\\.)*)"|'([^']*)')""",
)


def extract_commit_message(command: str) -> str | None:
    """Extract the -m argument value from a git commit command."""
    heredoc = _HEREDOC_MSG_RE.search(command)
    if heredoc:
        return heredoc.group(1)
    m = _SIMPLE_MSG_RE.search(command)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


_ESCAPE_HATCH_RE = re.compile(r"^\[(release|chore)\]", re.IGNORECASE)


def is_escape_hatch_commit(command: str) -> bool:
    msg = extract_commit_message(command)
    if msg is None:
        return False
    return bool(_ESCAPE_HATCH_RE.match(msg))


def is_worktree_clean(cwd: str) -> bool:
    r = _git(["git", "status", "--porcelain"], cwd)
    return r.returncode == 0 and r.stdout.strip() == ""


def branch_exists(cwd: str, name: str) -> bool:
    r = _git(["git", "rev-parse", "--verify", f"refs/heads/{name}"], cwd)
    return r.returncode == 0


def _checkout_or_exit(cwd: str, branch: str) -> None:
    r = _git(["git", "checkout", branch], cwd)
    if r.returncode != 0:
        print(f"Failed to checkout {branch}: {r.stderr}", file=sys.stderr)
        sys.exit(1)


def _fast_forward_if_safe(cwd: str, branch: str, base: str) -> None:
    """Fast-forward `branch` to `base` when `branch` is an ancestor of `base`.

    No-op when `branch` has unique commits or has diverged — silent
    rebase could lose work. The branch must already be checked out.
    Logs a stderr note on a successful fast-forward so the user knows
    the ref moved under them.
    """
    r = _git(["git", "merge-base", "--is-ancestor", branch, base], cwd)
    if r.returncode != 0:
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
) -> str | None:
    """Create `name` or resume it if it already exists locally.

    Returns the branch name, or None when the configured branching
    stage is below `min_stage`. The base argument forks the new branch
    from a specific ref instead of HEAD; on resume, the existing branch
    fast-forwards to `base` when its tip is an ancestor of `base` so
    sprint-start scaffolds don't snap to a stale base mid-sprint.
    Branches with unique commits ahead of base are left alone.
    """
    if get_branching_stage(smm_dir) < min_stage:
        return None

    if branch_exists(cwd, name):
        _checkout_or_exit(cwd, name)
        if base is not None:
            _fast_forward_if_safe(cwd, name, base)
        return name

    if not is_worktree_clean(cwd):
        print("Working tree is dirty — commit or stash changes first", file=sys.stderr)
        sys.exit(1)

    cmd = ["git", "checkout", "-b", name]
    if base is not None:
        cmd.append(base)
    r = _git(cmd, cwd)
    if r.returncode != 0:
        print(f"Failed to create branch {name}: {r.stderr}", file=sys.stderr)
        sys.exit(1)

    return name


# Single source of truth: each create_*_branch enforces a min stage,
# and _print_or_skip renders the same threshold in its skip message.
# Sharing the values here prevents the inner enforcement and the outer
# message from drifting if a stage threshold ever moves.
_BRANCH_MIN_STAGE: dict[str, int] = {
    "story": 1,
    "sprint": 2,
    "plan": 2,
    "free": 1,
}


def create_story_branch(
    cwd: str, story_id: str, slug: str, smm_dir: Path
) -> str | None:
    """Returns branch name or None if below story min stage.

    Passes the resolved story base (sprint branch at stage 2+, otherwise
    primary) so resume can fast-forward a stale scaffold to the current
    base when safe — see _fast_forward_if_safe.
    """
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, story_id, slug)
    base = get_story_base_branch(smm_dir, cwd)
    return _create_or_resume_branch(
        cwd, name, smm_dir, min_stage=_BRANCH_MIN_STAGE["story"], base=base
    )


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
        cwd, name, smm_dir, min_stage=_BRANCH_MIN_STAGE["sprint"], base=base
    )
    if result is not None and sprint_store.sprint_exists(smm_dir):
        sprint_store.set_branch(smm_dir, result)
    return result


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def create_free_branch(cwd: str, slug: str, smm_dir: Path) -> str | None:
    """Create or resume <user>/free-YYYY-MM-DD-<slug> off the primary branch.

    Free branches are scratch work outside of plans/sprints. Date is UTC.
    Returns None when branching stage < 1 (Stage 0 has no branch
    discipline). Per BRANCH_LIFECYCLE design, free-branch protection
    activates at Stage 1+ to keep exploratory work off protected branches.
    """
    user_ns = identity.user_namespace(cwd)
    name = f"{user_ns}/free-{_utc_today_iso()}-{_slugify(slug)}"
    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=_BRANCH_MIN_STAGE["free"],
        base=get_primary_branch(smm_dir),
    )


def list_free_branches(cwd: str) -> list[str]:
    """Return free branches owned by the current user, excluding HEAD."""
    user_ns = identity.user_namespace(cwd)
    current = identity.get_current_branch(cwd)
    return [b for b in _match_local_branches(cwd, f"{user_ns}/free-*") if b != current]


def create_plan_branch(cwd: str, slug: str, smm_dir: Path) -> str | None:
    """Create or resume <user>/plan-<slug> off the primary branch.

    Records the branch into execution_plan.json on BOTH create and
    resume paths so a regenerated plan still links to its branch and
    any prior slug drift is fixed idempotently. Mirrors the sprint
    primitive's atomic re-record. Returns None when stage < plan.
    """
    user_ns = identity.user_namespace(cwd)
    name = f"{user_ns}/plan-{_slugify(slug)}"
    result = _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=_BRANCH_MIN_STAGE["plan"],
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


def delete_branch(cwd: str, name: str) -> bool:
    r = _git(["git", "branch", "-d", name], cwd)
    return r.returncode == 0


def _print_or_skip(result: str | None, min_stage: int) -> int:
    print(result if result else f"Skipped (stage < {min_stage})")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_story_branch(args.cwd, args.story, args.slug, Path(args.smm_dir)),
        _BRANCH_MIN_STAGE["story"],
    )


def _resolve_target(args: argparse.Namespace) -> str:
    """Use --target when provided; else compute via get_merge_target."""
    return args.target or get_merge_target(Path(args.smm_dir), args.cwd)


def _cmd_delete(args: argparse.Namespace) -> int:
    ok = delete_branch(args.cwd, args.branch)
    return 0 if ok else 1


def _cmd_create_sprint(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_sprint_branch(args.cwd, args.sprint, args.slug, Path(args.smm_dir)),
        _BRANCH_MIN_STAGE["sprint"],
    )


def _cmd_get_base(args: argparse.Namespace) -> int:
    result = get_story_base_branch(Path(args.smm_dir), args.cwd)
    print(result)
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    stage = get_branching_stage(Path(args.smm_dir))
    print(stage)
    return 0


def _cmd_get_primary(args: argparse.Namespace) -> int:
    print(get_primary_branch(Path(args.smm_dir)))
    return 0


def _cmd_get_target(args: argparse.Namespace) -> int:
    print(get_merge_target(Path(args.smm_dir), args.cwd))
    return 0


def _cmd_merge_branch(args: argparse.Namespace) -> int:
    merge_branch(args.cwd, args.branch, _resolve_target(args))
    return 0


def _cmd_create_plan(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_plan_branch(args.cwd, args.slug, Path(args.smm_dir)),
        _BRANCH_MIN_STAGE["plan"],
    )


def _cmd_create_free(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_free_branch(args.cwd, args.slug, Path(args.smm_dir)),
        _BRANCH_MIN_STAGE["free"],
    )


def _cmd_list_free(args: argparse.Namespace) -> int:
    for b in list_free_branches(args.cwd):
        print(b)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Branch lifecycle operations")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a story branch")
    p_create.add_argument("--cwd", required=True)
    p_create.add_argument("--story", required=True)
    p_create.add_argument("--slug", required=True)
    p_create.set_defaults(func=_cmd_create)

    p_delete = sub.add_parser("delete", help="Delete a branch")
    p_delete.add_argument("--cwd", required=True)
    p_delete.add_argument("--branch", required=True)
    p_delete.set_defaults(func=_cmd_delete)

    p_csprint = sub.add_parser("create-sprint", help="Create a sprint branch")
    p_csprint.add_argument("--cwd", required=True)
    p_csprint.add_argument("--sprint", required=True)
    p_csprint.add_argument("--slug", required=True)
    p_csprint.set_defaults(func=_cmd_create_sprint)

    p_base = sub.add_parser("get-base", help="Print story base branch")
    p_base.add_argument("--cwd", required=True)
    p_base.set_defaults(func=_cmd_get_base)

    p_stage = sub.add_parser("stage", help="Print branching stage")
    p_stage.set_defaults(func=_cmd_stage)

    p_get_primary = sub.add_parser(
        "get-primary", help="Print primary integration branch"
    )
    p_get_primary.set_defaults(func=_cmd_get_primary)

    p_get_target = sub.add_parser("get-target", help="Print merge target")
    p_get_target.add_argument("--cwd", required=True)
    p_get_target.set_defaults(func=_cmd_get_target)

    p_merge_branch = sub.add_parser(
        "merge-branch", help="Merge any branch (sprint or plan) into a target"
    )
    p_merge_branch.add_argument("--cwd", required=True)
    p_merge_branch.add_argument("--branch", required=True)
    p_merge_branch.add_argument("--target", default=None)
    p_merge_branch.set_defaults(func=_cmd_merge_branch)

    p_create_plan = sub.add_parser("create-plan", help="Create or resume a plan branch")
    p_create_plan.add_argument("--cwd", required=True)
    p_create_plan.add_argument("--slug", required=True)
    p_create_plan.set_defaults(func=_cmd_create_plan)

    p_create_free = sub.add_parser("create-free", help="Create or resume a free branch")
    p_create_free.add_argument("--cwd", required=True)
    p_create_free.add_argument("--slug", required=True)
    p_create_free.set_defaults(func=_cmd_create_free)

    p_list_free = sub.add_parser("list-free", help="List the user's free branches")
    p_list_free.add_argument("--cwd", required=True)
    p_list_free.set_defaults(func=_cmd_list_free)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
