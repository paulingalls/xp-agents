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
    plan_cli.py archive --smm-dir DIR
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import execution_plan_store as store


def _cmd_exists(args: argparse.Namespace) -> int:
    return 0 if store.plan_exists(args.smm_dir) else 1


def _cmd_has_remaining(args: argparse.Namespace) -> int:
    return 0 if store.has_remaining_work(args.smm_dir) else 1


def _cmd_count(args: argparse.Namespace) -> int:
    counts = store.count_milestones(args.smm_dir)
    print(
        f"planned={counts['planned']} "
        f"in_progress={counts['in_progress']} "
        f"delivered={counts['delivered']}"
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
    plan = store.load_plan(args.smm_dir)
    if plan is None:
        print("No execution plan found.", file=sys.stderr)
        return 1

    milestone_num = args.milestone_number
    matches = [m for m in plan["milestones"] if m["number"] == milestone_num]
    if not matches:
        print(
            f"No milestone with number {milestone_num}",
            file=sys.stderr,
        )
        return 1

    status = args.status
    if status == "delivered" and not args.delivered_sprint:
        print(
            "--delivered-sprint required for delivered status",
            file=sys.stderr,
        )
        return 1

    milestone = matches[0]
    milestone["status"] = status
    if status == "delivered":
        milestone["delivered_sprint"] = args.delivered_sprint
    elif milestone.get("delivered_sprint"):
        milestone["delivered_sprint"] = None

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execution plan CLI",
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
        choices=["planned", "in-progress", "delivered"],
        help="New status",
    )
    update_p.add_argument(
        "--delivered-sprint",
        help="Sprint ID (required for delivered status)",
    )

    sub.add_parser("archive", help="Archive plan to plans/ folder")

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
        "archive": _cmd_archive,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
