#!/usr/bin/env python3
"""CLI for sprint operations.

Thin wrapper over sprint_store.py for shell scripts and skills.
Python scripts should import the store directly.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sprint_store as store


def _cmd_exists(args: argparse.Namespace) -> int:
    return 0 if store.sprint_exists(args.smm_dir) else 1


def _cmd_has_active(args: argparse.Namespace) -> int:
    return 0 if store.has_active_stories(args.smm_dir) else 1


def _cmd_is_complete(args: argparse.Namespace) -> int:
    return 0 if store.is_complete(args.smm_dir) else 1


def _cmd_count(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("ready=0 in-progress=0 done=0 deferred=0")
        return 0
    counts = store.count_by_status(sprint)
    print(
        f"ready={counts['ready']} "
        f"in-progress={counts['in-progress']} "
        f"done={counts['done']} "
        f"deferred={counts['deferred']}"
    )
    return 0


def _cmd_velocity(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    v = store.compute_velocity(sprint)
    print(
        f"planned={v['stories_planned']} "
        f"delivered={v['stories_delivered']} "
        f"carried={v['stories_carried']}"
    )
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    print(store.render_markdown(sprint))
    return 0


def _cmd_render_stories(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    print(store.render_story_sections(sprint, args.story_ids))
    return 0


def _cmd_count_status(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("0")
        return 0
    counts = store.count_by_status(sprint)
    print(counts.get(args.status, 0))
    return 0


def _cmd_next_id(args: argparse.Namespace) -> int:
    print(store.next_sprint_id(args.smm_dir))
    return 0


def _cmd_list_stories(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    status = getattr(args, "status", None)
    stories = store.list_stories(sprint, status=status)
    for s in stories:
        print(f"{s['id']}: {s['title']} [{s['status']}]")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    try:
        store.save_sprint(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_add_story(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        story = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    sprint["stories"].append(story)
    try:
        store.save_sprint(args.smm_dir, sprint)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_update_story(args: argparse.Namespace) -> int:
    try:
        store.update_story_status(args.smm_dir, args.story_id, args.status)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sprint CLI",
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("exists", help="Check if sprint exists")
    sub.add_parser("has-active", help="Check for active stories")
    sub.add_parser("is-complete", help="Check if sprint is complete")
    sub.add_parser("count", help="Count stories by status")
    sub.add_parser("next-id", help="Next sprint ID")

    cs_p = sub.add_parser("count-status", help="Count stories with a specific status")
    cs_p.add_argument(
        "status",
        choices=["ready", "in-progress", "done", "deferred"],
        help="Status to count",
    )

    sub.add_parser("velocity", help="Velocity metrics")
    sub.add_parser("render", help="Render as markdown")

    render_s = sub.add_parser("render-stories", help="Render specific stories")
    render_s.add_argument("story_ids", nargs="+", help="Story IDs to render")

    list_s = sub.add_parser(
        "list-stories", help="List stories (optional status filter)"
    )
    list_s.add_argument(
        "--status",
        choices=["ready", "in-progress", "done", "deferred"],
        help="Filter by status",
    )

    sub.add_parser("create", help="Create sprint from stdin")
    sub.add_parser("add-story", help="Add story from stdin")

    update_p = sub.add_parser("update-story", help="Update story status")
    update_p.add_argument("story_id", help="Story ID")
    update_p.add_argument(
        "status",
        choices=["ready", "in-progress", "done", "deferred"],
        help="New status",
    )

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "has-active": _cmd_has_active,
        "is-complete": _cmd_is_complete,
        "count": _cmd_count,
        "count-status": _cmd_count_status,
        "next-id": _cmd_next_id,
        "velocity": _cmd_velocity,
        "render": _cmd_render,
        "render-stories": _cmd_render_stories,
        "list-stories": _cmd_list_stories,
        "create": _cmd_create,
        "add-story": _cmd_add_story,
        "update-story": _cmd_update_story,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
