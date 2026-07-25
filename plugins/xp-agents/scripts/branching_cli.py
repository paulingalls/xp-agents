#!/usr/bin/env python3
"""CLI dispatch for branch lifecycle operations.

Thin CLI layer over branching.py library functions. All callers
invoke `python3 branching.py <subcommand>` — branching.py's
__main__ guard delegates here.
"""

import argparse
import json
import sys
from pathlib import Path

import branch_queries
import branching
import branching_cli_accept
import identity

# Re-exported by identity for code split out of this module, mirroring
# branching.py's back-compat blocks: `branching_cli.<name>` still resolves for
# the SKILLs' dispatch table and for tests that reach for the privates.
from branching_cli_target import (  # noqa: F401
    _cmd_delete,
    _cmd_merge_branch,
    _delete_refusal,
    _is_current_sprint_story_branch,
    _resolve_target,
)
from branching_cli_worktree import (
    _cmd_find_closing_teammate_worktree,
    _cmd_find_teammate_worktree,
    _cmd_list_teammate_worktree_paths,
    _cmd_resolve_review_worktree,
)


def _print_or_skip(result: str | None, min_stage: int, *, resumed: bool = False) -> int:
    if result:
        prefix = "resumed" if resumed else "created"
        print(f"{prefix}: {result}")
    else:
        print(f"Skipped (stage < {min_stage})")
    return 0


def _blank_base_refused(args: argparse.Namespace, cmd: str, resolves: str) -> bool:
    """True (having explained itself on stderr) when --base was passed but blank.

    argparse yields "" for `--base ""`, not None, so a blank base sails past
    every downstream `base is None` check (which would have resolved and
    verified a real one) and reaches git as an empty ref. On the create arm git
    rejects it; on the RESUME arm nothing does — the branch is checked out,
    `_fast_forward_if_safe` no-ops against the empty ref (`git merge-base
    --is-ancestor <branch> ""` merely exits non-zero), and we print `resumed:`
    and exit 0. A caller whose "$BASE" came back empty is told all is well.

    Shared by BOTH --base-taking commands, not just `create`. `create` is where
    a blank base is likeliest — the story SKILLs pass `--base "$BASE"` from a
    command substitution that returns empty when its resolver refuses, and they
    do not run under `set -e` — but `create-free` takes the same flag and has
    the same silent resume arm, so guarding one leg and not the other just moves
    the hole. No git ref is empty or whitespace-only, so refusing both is free:
    a blank base is a caller bug, not a request.
    """
    if args.base is None or args.base.strip():
        return False
    sys.stderr.write(
        f"{cmd}: --base was empty. Pass a real ref, or omit --base entirely "
        f"to resolve {resolves}.\n"
    )
    return True


def _cmd_create(args: argparse.Namespace) -> int:
    if _blank_base_refused(args, "create", "the story base from the sprint"):
        return 1
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd, smm_dir)
    name = branching.branch_name(user_ns, args.story, args.slug)
    # Mirror create_story_branch's recorded-branch resolution (same stage
    # guard) so a reslice-retitle that RESUMES the recorded branch is reported
    # as resumed:, not created: — parity with _cmd_create_sprint, which
    # resolves via resolve_sprint_branch_name for exactly this reason.
    if branching.get_branching_stage(smm_dir) >= branching.BRANCH_MIN_STAGE["story"]:
        name = branching._recorded_story_branch(args.cwd, smm_dir, args.story) or name
    existed = branching.branch_exists(args.cwd, name)
    try:
        result = branching.create_story_branch(
            args.cwd, args.story, args.slug, smm_dir, base=args.base
        )
    except ValueError as exc:
        # An unresolvable story base (sprint at stage 2+ whose branch is gone).
        # That message IS the product of the refusal — it names the sprint, both
        # candidate branches, the primary it would not silently fall back to, and
        # the way out. Print it like every other ValueError in this CLI rather
        # than letting a traceback bury the one thing the user has to read.
        sys.stderr.write(f"{exc}\n")
        return 1
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["story"], resumed=existed)


def _cmd_create_sprint(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    # Ask the resolver, not the slug: on a re-slice create_sprint_branch resumes
    # the branch RECORDED for this sprint_id, and the slug-built name it no
    # longer uses never exists — which would report a resume as `created:` and
    # strand SKILL.md Step 8's adopt/rename prompt (it routes on that token).
    name = branching.resolve_sprint_branch_name(
        args.cwd, args.sprint, args.slug, smm_dir
    )
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_sprint_branch(args.cwd, args.sprint, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["sprint"], resumed=existed)


def _cmd_get_base(args: argparse.Namespace) -> int:
    """Print the story base branch. ``--required`` refuses to guess.

    One subcommand, two postures, because one answer genuinely serves both:
    callers that BRANCH FROM or MERGE INTO the base (xp-assign, xp-schedule,
    xp-story-close) pass --required and must halt rather than act on a
    degraded primary; callers that only PROBE (xp-quality-review's diff range)
    take the default and are right to degrade.

    The default is unchanged, deliberately — the degrading callers carry zero
    risk from this flag existing.

    On refusal: NOTHING on stdout, the reason on stderr, exit 1. Empty stdout
    is a HARD CONTRACT — the story-close preload does BASE=$(... --required),
    so any byte here becomes the ref it merges into. That is also why the two
    streams stay separate and the caller keys off the EXIT CODE, never
    `2>&1`: _common.log_hook_error mirrors to stderr always, and can fire on
    the SUCCESS path (auto-promote against a read-only SMM), so folding stderr
    into stdout would splice a warning into a branch name.
    """
    smm_dir = Path(args.smm_dir)
    if not args.required:
        print(branching.get_story_base_branch(smm_dir, args.cwd))
        return 0
    try:
        base = branching.get_story_base_branch_required(smm_dir, args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    print(base)
    return 0


def _cmd_stage(args: argparse.Namespace) -> int:
    stage = branching.get_branching_stage(Path(args.smm_dir))
    print(stage)
    return 0


def _cmd_get_primary(args: argparse.Namespace) -> int:
    print(branching.get_primary_branch(Path(args.smm_dir)))
    return 0


def _cmd_get_target(args: argparse.Namespace) -> int:
    print(branching.get_merge_target(Path(args.smm_dir), args.cwd))
    return 0


def _cmd_extract_story_id(args: argparse.Namespace) -> int:
    """Print story-NNN from `<user>/story-NNN-<slug>`. Empty if no match.

    Always exits 0 — empty stdout signals "not a story branch" cleanly
    so SKILL.md callers can `[ -n "$STORY_ID" ]` gate without needing
    to distinguish error vs no-match exit codes.
    """
    print(identity.extract_story_id(args.branch) or "")
    return 0


def _cmd_create_plan(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd, smm_dir)
    name = branching.plan_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_plan_branch(args.cwd, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["plan"], resumed=existed)


def _cmd_create_free(args: argparse.Namespace) -> int:
    if _blank_base_refused(args, "create-free", "the merge target"):
        return 1
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd, smm_dir)
    name = branching.free_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    try:
        result = branching.create_free_branch(
            args.cwd, args.slug, smm_dir, base=args.base
        )
    except ValueError as exc:
        # A `--base` git cannot resolve. Print it like `create` does, rather
        # than let a traceback bury the ref that was misspelled.
        sys.stderr.write(f"{exc}\n")
        return 1
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["free"], resumed=existed)


def _cmd_list_free(args: argparse.Namespace) -> int:
    for b in branching.list_free_branches(args.cwd, Path(args.smm_dir)):
        print(b)
    return 0


def _cmd_list_story_orphans(args: argparse.Namespace) -> int:
    """Print story branches not backed by an active sprint story.

    Active = any non-terminal status (see
    ``sprint_schema.ACTIVE_STORY_STATUSES``); the closing/reviewing
    branches stay alive for /xp-story-close merge and /xp-accept
    verification respectively and are NOT orphan.
    """
    for b in branch_queries.list_orphan_story_branches(args.cwd, Path(args.smm_dir)):
        print(b)
    return 0


def _cmd_check_divergence(args: argparse.Namespace) -> int:
    result = branching.check_plan_divergence(
        args.cwd, Path(args.smm_dir), args.threshold
    )
    if result is None:
        print("No plan branch found")
        return 0
    print(json.dumps(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Branch lifecycle operations")
    parser.add_argument("--smm-dir", required=True, help="SMM directory path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create a story branch")
    p_create.add_argument("--cwd", required=True)
    p_create.add_argument("--story", required=True)
    p_create.add_argument("--slug", required=True)
    p_create.add_argument("--base", default=None, help="Fork from this ref")
    p_create.set_defaults(func=_cmd_create)

    p_delete = sub.add_parser("delete", help="Delete a branch")
    p_delete.add_argument("--cwd", required=True)
    p_delete.add_argument("--branch", required=True)
    p_delete.add_argument(
        "--target",
        default=None,
        help=(
            "The branch it was merged into. Defaults to this sprint's story "
            "base for a branch the sprint records, else to the merge target. "
            "Enables the ancestry-proven force-delete for a branch that is "
            "fully merged but has drifted from its upstream tracking ref."
        ),
    )
    p_delete.set_defaults(func=_cmd_delete)

    p_csprint = sub.add_parser("create-sprint", help="Create a sprint branch")
    p_csprint.add_argument("--cwd", required=True)
    p_csprint.add_argument("--sprint", required=True)
    p_csprint.add_argument("--slug", required=True)
    p_csprint.set_defaults(func=_cmd_create_sprint)

    p_base = sub.add_parser("get-base", help="Print story base branch")
    p_base.add_argument("--cwd", required=True)
    p_base.add_argument(
        "--required",
        action="store_true",
        help=(
            "Refuse to degrade: exit 1 with an empty stdout and a reason on "
            "stderr when the story base cannot be honestly resolved. For "
            "callers that branch from or merge into the answer."
        ),
    )
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
    p_merge_branch.add_argument(
        "--target",
        default=None,
        help=(
            "The branch to merge into. Defaults to this sprint's story base "
            "for a branch the sprint records, else to the merge target; "
            "refuses rather than guess when that base cannot be resolved."
        ),
    )
    p_merge_branch.set_defaults(func=_cmd_merge_branch)

    p_create_plan = sub.add_parser("create-plan", help="Create or resume a plan branch")
    p_create_plan.add_argument("--cwd", required=True)
    p_create_plan.add_argument("--slug", required=True)
    p_create_plan.set_defaults(func=_cmd_create_plan)

    p_create_free = sub.add_parser("create-free", help="Create or resume a free branch")
    p_create_free.add_argument("--cwd", required=True)
    p_create_free.add_argument("--slug", required=True)
    p_create_free.add_argument("--base", default=None, help="Fork from this ref")
    p_create_free.set_defaults(func=_cmd_create_free)

    p_list_free = sub.add_parser("list-free", help="List the user's free branches")
    p_list_free.add_argument("--cwd", required=True)
    p_list_free.set_defaults(func=_cmd_list_free)

    p_list_orphans = sub.add_parser(
        "list-story-orphans", help="List orphan story branches"
    )
    p_list_orphans.add_argument("--cwd", required=True)
    p_list_orphans.set_defaults(func=_cmd_list_story_orphans)

    p_xsid = sub.add_parser(
        "extract-story-id",
        help="Print story-NNN from a `<user>/story-NNN[-<slug>]` branch",
    )
    p_xsid.add_argument("--branch", required=True)
    p_xsid.set_defaults(func=_cmd_extract_story_id)

    p_ltwp = sub.add_parser(
        "list-teammate-worktree-paths",
        help="List live teammate worktrees as `story-id<TAB>abs-path` rows",
    )
    p_ltwp.add_argument("--cwd", required=True)
    p_ltwp.set_defaults(func=_cmd_list_teammate_worktree_paths)

    p_ftw = sub.add_parser(
        "find-teammate-worktree",
        help="Print live teammate worktree name for a story id (empty if none)",
    )
    p_ftw.add_argument("--story-id", required=True)
    p_ftw.add_argument("--cwd", required=True)
    p_ftw.set_defaults(func=_cmd_find_teammate_worktree)

    p_fctw = sub.add_parser(
        "find-closing-teammate-worktree",
        help=(
            "Print `<abs-path><TAB><branch>` for the worktree of the in-reviewing story"
        ),
    )
    p_fctw.add_argument("--cwd", required=True)
    p_fctw.set_defaults(func=_cmd_find_closing_teammate_worktree)

    p_rrw = sub.add_parser(
        "resolve-review-worktree",
        help=(
            "Print `<abs-path><TAB><branch>` for /xp-quality-review's target "
            "worktree — invoker's own worktree first, else the closing-story scan"
        ),
    )
    p_rrw.add_argument("--cwd", required=True)
    p_rrw.set_defaults(func=_cmd_resolve_review_worktree)

    p_div = sub.add_parser("check-divergence", help="Check plan branch divergence")
    p_div.add_argument("--cwd", required=True)
    p_div.add_argument("--threshold", type=int, default=10)
    p_div.set_defaults(func=_cmd_check_divergence)

    branching_cli_accept.register(sub)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
