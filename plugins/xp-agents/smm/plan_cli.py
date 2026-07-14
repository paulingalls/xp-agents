#!/usr/bin/env python3
"""CLI for execution plan operations.

Thin wrapper over execution_plan_store.py for shell scripts and
Claude Code skills. Python scripts should import the store directly.

Usage:
    plan_cli.py exists --smm-dir DIR
    plan_cli.py has-remaining --smm-dir DIR
    plan_cli.py count --smm-dir DIR
    plan_cli.py render --smm-dir DIR
    plan_cli.py create --smm-dir DIR          < plan.json
    plan_cli.py add-source --smm-dir DIR      < source.json
    plan_cli.py add-milestone --smm-dir DIR   < milestone.json
    plan_cli.py set-overview --smm-dir DIR     < overview.txt
    plan_cli.py update-status N STATUS --smm-dir DIR
    plan_cli.py edit-milestone N --smm-dir DIR   < patch.json
    plan_cli.py archive --smm-dir DIR
    plan_cli.py set-branch NAME --smm-dir DIR
    plan_cli.py get-branch --smm-dir DIR
    plan_cli.py is-plan-complete --smm-dir DIR
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import execution_plan_store as store
from execution_plan_schema import VALID_MILESTONE_STATUSES


def _cmd_exists(args: argparse.Namespace) -> int:
    return 0 if store.plan_exists(args.smm_dir) else 1


def _cmd_has_remaining(args: argparse.Namespace) -> int:
    return 0 if store.has_remaining_work(args.smm_dir) else 1


def _cmd_count(args: argparse.Namespace) -> int:
    counts = store.count_milestones(args.smm_dir)
    print(
        f"planned={counts['planned']} "
        f"in-progress={counts['in-progress']} "
        f"delivered={counts['delivered']} "
        f"deferred={counts['deferred']}"
    )
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    print(store.render_markdown(plan))
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    try:
        store.save_plan(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_add_source(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        source = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    plan["sources"].append(source)
    try:
        store.save_plan(args.smm_dir, plan)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_add_milestone(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        milestone = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    plan["milestones"].append(milestone)
    try:
        store.save_plan(args.smm_dir, plan)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_set_overview(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    plan["overview"] = sys.stdin.read().strip()
    try:
        store.save_plan(args.smm_dir, plan)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_update_status(args: argparse.Namespace) -> int:
    if args.status == "delivered" and not args.delivered_sprint:
        print(
            "--delivered-sprint required for delivered status",
            file=sys.stderr,
        )
        return 1
    try:
        store.update_milestone_status(
            args.smm_dir,
            args.milestone_number,
            args.status,
            delivered_sprint=args.delivered_sprint,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _cmd_edit_milestone(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1

    milestone_num = args.milestone_number
    milestone = store.find_milestone(plan, milestone_num)
    if milestone is None:
        print(f"No milestone with number {milestone_num}", file=sys.stderr)
        return 1

    # "Never modify a delivered milestone" was prose-only, and prose does not
    # stop a patch. Delivery is recorded by the sprint reviewer through
    # update-status (the only writer of delivered_sprint); an edit-milestone
    # patch would silently rewrite the shipped record behind it.
    if milestone["status"] == "delivered":
        print(
            f"Milestone {milestone_num} is delivered — only update-status may "
            "change it.",
            file=sys.stderr,
        )
        return 1

    raw = sys.stdin.read()
    try:
        patch = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    milestone.update(patch)
    try:
        store.save_plan(args.smm_dir, plan)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    result = store.archive(args.smm_dir)
    if result is None:
        print("No execution plan to archive.", file=sys.stderr)
        return 1
    print(f"Archived to: {result}")
    return 0


def _cmd_set_branch(args: argparse.Namespace) -> int:
    # Empty-string-clears is a CLI affordance; the store contract is null-or-valid-name.
    # Delegate to the store helper so this mutate path grandfathers the
    # surfaces_touched FK (enforce_budget=False) — re-saving the whole plan
    # here with strict enforcement would block on post-authoring surface drift.
    try:
        store.set_branch(args.smm_dir, args.name or None)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_get_branch(args: argparse.Namespace) -> int:
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    print(plan.get("branch") or "")
    return 0


def _cmd_is_plan_complete(args: argparse.Namespace) -> int:
    """Exit codes: 0 = complete, 1 = incomplete, 1 + stderr = no plan."""
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1
    return 0 if store.plan_is_complete(plan) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execution plan CLI",
        epilog=(
            "Examples:\n"
            "  cat plan.json | plan_cli.py --smm-dir DIR create\n"
            '  echo \'{"goal":"..."}\' | plan_cli.py'
            " --smm-dir DIR edit-milestone 3\n"
            "  plan_cli.py --smm-dir DIR"
            " update-status 3 delivered --delivered-sprint s11\n"
            "  plan_cli.py --smm-dir DIR render"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("exists", help="Check if plan exists")
    sub.add_parser("has-remaining", help="Check for remaining work")
    sub.add_parser("count", help="Count milestones by status")
    sub.add_parser("render", help="Render plan as markdown")
    sub.add_parser("create", help="Create plan from stdin JSON")
    sub.add_parser("add-source", help="Add source from stdin JSON")
    sub.add_parser("add-milestone", help="Add milestone from stdin JSON")
    sub.add_parser("set-overview", help="Set overview from stdin text")

    update_p = sub.add_parser("update-status", help="Update milestone status")
    update_p.add_argument("milestone_number", type=int, help="Milestone number")
    update_p.add_argument(
        "status",
        choices=sorted(VALID_MILESTONE_STATUSES),
        help="New status",
    )
    update_p.add_argument(
        "--delivered-sprint",
        help="Sprint ID (required for delivered status)",
    )

    edit_p = sub.add_parser(
        "edit-milestone", help="Edit milestone fields from stdin JSON"
    )
    edit_p.add_argument("milestone_number", type=int, help="Milestone number")

    sub.add_parser("archive", help="Archive plan to plans/ folder")

    set_branch_p = sub.add_parser(
        "set-branch", help="Set the plan's branch (empty string clears)"
    )
    set_branch_p.add_argument("name", help="Branch name; empty string clears")

    sub.add_parser("get-branch", help="Print the plan's branch (empty if null)")
    sub.add_parser(
        "is-plan-complete",
        help="Exit 0 when all milestones delivered/deferred, 1 otherwise",
    )

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "has-remaining": _cmd_has_remaining,
        "count": _cmd_count,
        "render": _cmd_render,
        "create": _cmd_create,
        "add-source": _cmd_add_source,
        "add-milestone": _cmd_add_milestone,
        "set-overview": _cmd_set_overview,
        "update-status": _cmd_update_status,
        "edit-milestone": _cmd_edit_milestone,
        "archive": _cmd_archive,
        "set-branch": _cmd_set_branch,
        "get-branch": _cmd_get_branch,
        "is-plan-complete": _cmd_is_plan_complete,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
