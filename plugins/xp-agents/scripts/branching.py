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
from collections.abc import Callable
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


def _recorded_plan_branch(cwd: str, smm_dir: Path) -> str | None:
    """Return execution_plan.branch when set AND it exists locally."""
    plan = execution_plan_store.load_plan(smm_dir)
    if plan is None:
        return None
    plan_branch = plan.get("branch")
    if plan_branch and branch_exists(cwd, plan_branch):
        return plan_branch
    return None


def get_merge_target(smm_dir: Path, cwd: str) -> str:
    """Return the branch to merge into.

    Plan branch when execution_plan.branch is recorded AND the branch
    exists locally; otherwise the primary integration branch.
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


def _create_or_resume_branch(
    cwd: str,
    name: str,
    smm_dir: Path,
    min_stage: int,
    *,
    base: str | None = None,
    on_create: Callable[[], None] | None = None,
) -> str | None:
    """Create `name` or resume it if it already exists locally.

    Returns the branch name, or None when the configured branching
    stage is below `min_stage`. The base argument forks the new branch
    from a specific ref instead of HEAD; on_create runs after a fresh
    branch is created (skipped on resume).
    """
    if get_branching_stage(smm_dir) < min_stage:
        return None

    if branch_exists(cwd, name):
        _checkout_or_exit(cwd, name)
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

    if on_create is not None:
        on_create()

    return name


def create_story_branch(
    cwd: str, story_id: str, slug: str, smm_dir: Path
) -> str | None:
    """Returns branch name or None if Stage 0."""
    user_ns = identity.user_namespace(cwd)
    name = branch_name(user_ns, story_id, slug)
    return _create_or_resume_branch(cwd, name, smm_dir, min_stage=1)


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
    result = _create_or_resume_branch(cwd, name, smm_dir, min_stage=2, base=base)
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
        cwd, name, smm_dir, min_stage=1, base=get_primary_branch(smm_dir)
    )


def list_free_branches(cwd: str) -> list[str]:
    """Return free branches owned by the current user, excluding HEAD."""
    user_ns = identity.user_namespace(cwd)
    pattern = f"refs/heads/{user_ns}/free-*"
    r = _git(
        ["git", "for-each-ref", "--format=%(refname:short)", pattern],
        cwd,
    )
    if r.returncode != 0:
        return []
    current = identity.get_current_branch(cwd)
    return [b for b in r.stdout.splitlines() if b and b != current]


def create_plan_branch(cwd: str, slug: str, smm_dir: Path) -> str | None:
    """Create or resume <user>/plan-<slug> off the primary branch.

    Records the branch in execution_plan.json on first creation only;
    resume preserves any existing recorded value.
    Returns None when branching stage < 2.
    """
    user_ns = identity.user_namespace(cwd)
    name = f"{user_ns}/plan-{_slugify(slug)}"

    def _record_in_plan() -> None:
        if execution_plan_store.plan_exists(smm_dir):
            execution_plan_store.set_branch(smm_dir, name)

    return _create_or_resume_branch(
        cwd,
        name,
        smm_dir,
        min_stage=2,
        base=get_primary_branch(smm_dir),
        on_create=_record_in_plan,
    )


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


def merge_story_branch(cwd: str, story_branch: str, target: str = "main") -> None:
    _merge_into_target(cwd, story_branch, target)


def merge_sprint_branch(cwd: str, sprint_branch: str, target: str = "main") -> None:
    _merge_into_target(cwd, sprint_branch, target)


def delete_branch(cwd: str, name: str) -> bool:
    r = _git(["git", "branch", "-d", name], cwd)
    return r.returncode == 0


def _print_or_skip(result: str | None, min_stage: int) -> int:
    print(result if result else f"Skipped (stage < {min_stage})")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_story_branch(args.cwd, args.story, args.slug, Path(args.smm_dir)),
        min_stage=1,
    )


def _cmd_merge(args: argparse.Namespace) -> int:
    merge_story_branch(args.cwd, args.branch, args.target)
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    ok = delete_branch(args.cwd, args.branch)
    return 0 if ok else 1


def _cmd_create_sprint(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_sprint_branch(args.cwd, args.sprint, args.slug, Path(args.smm_dir)),
        min_stage=2,
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


def _cmd_merge_sprint(args: argparse.Namespace) -> int:
    merge_sprint_branch(args.cwd, args.branch, args.target)
    return 0


def _cmd_create_plan(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_plan_branch(args.cwd, args.slug, Path(args.smm_dir)),
        min_stage=2,
    )


def _cmd_create_free(args: argparse.Namespace) -> int:
    return _print_or_skip(
        create_free_branch(args.cwd, args.slug, Path(args.smm_dir)),
        min_stage=1,
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

    p_merge = sub.add_parser("merge", help="Merge a story branch")
    p_merge.add_argument("--cwd", required=True)
    p_merge.add_argument("--branch", required=True)
    p_merge.add_argument("--target", default="main")
    p_merge.set_defaults(func=_cmd_merge)

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

    p_merge_sprint = sub.add_parser("merge-sprint", help="Merge a sprint branch")
    p_merge_sprint.add_argument("--cwd", required=True)
    p_merge_sprint.add_argument("--branch", required=True)
    p_merge_sprint.add_argument("--target", default="main")
    p_merge_sprint.set_defaults(func=_cmd_merge_sprint)

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
