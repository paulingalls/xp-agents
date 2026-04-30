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


def _print_or_skip(result: str | None, min_stage: int, *, resumed: bool = False) -> int:
    if result:
        prefix = "resumed" if resumed else "created"
        print(f"{prefix}: {result}")
    else:
        print(f"Skipped (stage < {min_stage})")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.branch_name(user_ns, args.story, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_story_branch(
        args.cwd, args.story, args.slug, Path(args.smm_dir), base=args.base
    )
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["story"], resumed=existed)


def _resolve_target(args: argparse.Namespace) -> str:
    return args.target or branching.get_merge_target(Path(args.smm_dir), args.cwd)


def _cmd_delete(args: argparse.Namespace) -> int:
    ok = branching.delete_branch(args.cwd, args.branch)
    return 0 if ok else 1


def _cmd_create_sprint(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.sprint_branch_name(user_ns, args.sprint, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_sprint_branch(args.cwd, args.sprint, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["sprint"], resumed=existed)


def _cmd_get_base(args: argparse.Namespace) -> int:
    result = branching.get_story_base_branch(Path(args.smm_dir), args.cwd)
    print(result)
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


def _cmd_merge_branch(args: argparse.Namespace) -> int:
    branching.merge_branch(args.cwd, args.branch, _resolve_target(args))
    return 0


def _cmd_create_plan(args: argparse.Namespace) -> int:
    smm_dir = Path(args.smm_dir)
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.plan_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_plan_branch(args.cwd, args.slug, smm_dir)
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["plan"], resumed=existed)


def _cmd_create_free(args: argparse.Namespace) -> int:
    user_ns = branching.identity.user_namespace(args.cwd)
    name = branching.free_branch_name(user_ns, args.slug)
    existed = branching.branch_exists(args.cwd, name)
    result = branching.create_free_branch(args.cwd, args.slug, Path(args.smm_dir))
    return _print_or_skip(result, branching.BRANCH_MIN_STAGE["free"], resumed=existed)


def _cmd_list_free(args: argparse.Namespace) -> int:
    for b in branching.list_free_branches(args.cwd):
        print(b)
    return 0


def _cmd_list_story_orphans(args: argparse.Namespace) -> int:
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

    p_list_orphans = sub.add_parser(
        "list-story-orphans", help="List orphan story branches"
    )
    p_list_orphans.add_argument("--cwd", required=True)
    p_list_orphans.set_defaults(func=_cmd_list_story_orphans)

    p_div = sub.add_parser("check-divergence", help="Check plan branch divergence")
    p_div.add_argument("--cwd", required=True)
    p_div.add_argument("--threshold", type=int, default=10)
    p_div.set_defaults(func=_cmd_check_divergence)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
