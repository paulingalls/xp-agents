#!/usr/bin/env python3
"""CLI for sprint operations.

Thin wrapper over sprint_store.py for shell scripts and skills.
Python scripts should import the store directly.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sprint_render as render
import sprint_store as store
import triage
from sprint_schema import VALID_STORY_STATUSES

# Sorted to keep argparse help output stable across runs (frozenset
# iteration order is not guaranteed). Adding a status to the schema
# automatically updates every choices array that uses this list.
_STATUS_CHOICES = sorted(VALID_STORY_STATUSES)


def _cmd_exists(args: argparse.Namespace) -> int:
    return 0 if store.sprint_exists(args.smm_dir) else 1


def _cmd_has_active(args: argparse.Namespace) -> int:
    return 0 if store.has_active_stories(args.smm_dir) else 1


def _cmd_is_complete(args: argparse.Namespace) -> int:
    return 0 if store.is_complete(args.smm_dir) else 1


def _cmd_next_in_progress(args: argparse.Namespace) -> int:
    story_id = store.next_in_progress_story_id(
        args.smm_dir, treat_as_done=set(args.treat_as_done)
    )
    if story_id is None:
        return 1
    print(story_id)
    return 0


def _cmd_next_scheduled(args: argparse.Namespace) -> int:
    story_id = store.next_scheduled_story_id(
        args.smm_dir, treat_as_done=set(args.treat_as_done)
    )
    if story_id is None:
        return 1
    print(story_id)
    return 0


def _cmd_scheduled_overlap(args: argparse.Namespace) -> int:
    return 0 if store.scheduled_file_domains_overlap(args.smm_dir) else 1


def _cmd_find_transitive_dependents(args: argparse.Namespace) -> int:
    deps = store.transitive_active_dependents(args.smm_dir, args.story_id)
    if deps:
        print(" ".join(deps))
    return 0


def _cmd_get_story_branch(args: argparse.Namespace) -> int:
    print(store.get_story_branch_name(args.smm_dir, args.story_id))
    return 0


def _cmd_get_story(args: argparse.Namespace) -> int:
    try:
        story = store.get_story(args.smm_dir, args.story_id)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(story, indent=2))
    return 0


def _cmd_count(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    counts = (
        store.count_by_status(sprint)
        if sprint is not None
        else {s: 0 for s in _STATUS_CHOICES}
    )
    # Stable order matching the schema-derived sorted list.
    print(" ".join(f"{s}={counts.get(s, 0)}" for s in _STATUS_CHOICES))
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
    print(render.render_markdown(sprint))
    return 0


def _cmd_render_stories(args: argparse.Namespace) -> int:
    sprint = store.load_sprint(args.smm_dir)
    if sprint is None:
        print("No sprint found.", file=sys.stderr)
        return 1
    print(render.render_story_sections(sprint, args.story_ids))
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


def _cmd_update_story_if(args: argparse.Namespace) -> int:
    """Atomic compare-and-swap on story status.

    Exits 0 when the on-disk status matched --expected and the write
    succeeded; 1 when the status differed (no-op, file untouched);
    2 on validation/missing-id/missing-sprint errors. Callers can
    distinguish "lost the race" (rc=1) from "bad input" (rc=2).
    """
    try:
        ok = store.update_story_status_if(
            args.smm_dir, args.story_id, expected=args.expected, new=args.new
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0 if ok else 1


def _cmd_edit_story(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        updates = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    try:
        store.edit_story(args.smm_dir, args.story_id, updates)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_validate_domain(args: argparse.Namespace) -> int:
    """Diff git-changed files (since base) against the story's declared
    file_domain. Exits 0 on clean match (or no commits since base);
    non-zero with stderr drift report when actual changes touch files
    outside the declared set.
    """
    try:
        story = store.get_story(args.smm_dir, args.story_id)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    declared = triage.extract_file_domain_paths(
        story.get("file_domain") or [], cwd=args.cwd
    )

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{args.base}...HEAD"],
            cwd=str(args.cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print("git diff timed out", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(f"git diff failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1

    actual = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    drift = sorted(actual - declared)
    if drift:
        print(
            f"drift: {len(drift)} file(s) outside declared file_domain: "
            + " ".join(drift),
            file=sys.stderr,
        )
        return 1

    print(f"clean: {len(actual)} file(s) match declared domain")
    return 0


def _cmd_update_story_branch(args: argparse.Namespace) -> int:
    try:
        store.set_story_branch(args.smm_dir, args.story_id, args.branch_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sprint CLI",
        epilog=(
            "Examples:\n"
            "  cat sprint.json | sprint_cli.py"
            " --smm-dir DIR create\n"
            "  sprint_cli.py --smm-dir DIR"
            " update-story story-001 in-progress\n"
            '  echo \'{"context":"new"}\' | sprint_cli.py'
            " --smm-dir DIR edit-story story-001\n"
            "  sprint_cli.py --smm-dir DIR"
            " list-stories --status ready\n"
            "  sprint_cli.py --smm-dir DIR render"
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

    sub.add_parser("exists", help="Check if sprint exists")
    sub.add_parser("has-active", help="Check for active stories")
    sub.add_parser("is-complete", help="Check if sprint is complete")
    nip_p = sub.add_parser(
        "next-in-progress",
        help="Lowest-id in-progress story whose deps are all done (exit 1 if none)",
    )
    nip_p.add_argument(
        "--treat-as-done",
        action="append",
        default=[],
        metavar="STORY_ID",
        help=(
            "Treat STORY_ID as if its status were 'done' for the dep check. "
            "Repeatable. Used by /xp-story-close Step 8 to surface a "
            "next-scheduled story whose dep is the just-closed story "
            "(still 'closing' at JIT-next time, not yet 'done')."
        ),
    )
    nsc_p = sub.add_parser(
        "next-scheduled",
        help="Lowest-id scheduled story whose deps are all done (exit 1 if none)",
    )
    nsc_p.add_argument(
        "--treat-as-done",
        action="append",
        default=[],
        metavar="STORY_ID",
        help="Same as next-in-progress: see that subcommand's help.",
    )
    sub.add_parser(
        "scheduled-overlap",
        help=(
            "Exit 0 if 2+ scheduled stories share file_domain paths "
            "(parallel teammates would conflict — auto-pick solo); "
            "exit 1 when disjoint or <2 scheduled stories"
        ),
    )
    sub.add_parser("count", help="Count stories by status")
    sub.add_parser("next-id", help="Next sprint ID")

    cs_p = sub.add_parser("count-status", help="Count stories with a specific status")
    cs_p.add_argument(
        "status",
        choices=_STATUS_CHOICES,
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
        choices=_STATUS_CHOICES,
        help="Filter by status",
    )

    sub.add_parser("create", help="Create sprint from stdin")
    sub.add_parser("add-story", help="Add story from stdin")

    edit_p = sub.add_parser("edit-story", help="Edit story fields from stdin JSON")
    edit_p.add_argument("story_id", help="Story ID to edit")

    update_p = sub.add_parser("update-story", help="Update story status")
    update_p.add_argument("story_id", help="Story ID")
    update_p.add_argument(
        "status",
        choices=_STATUS_CHOICES,
        help="New status",
    )

    usi_p = sub.add_parser(
        "update-story-if",
        help=(
            "Atomic compare-and-swap on story status. Exits 0 on success, "
            "1 when the on-disk status differed from --expected (no write), "
            "2 on validation errors. Used by xp-accept Step 1.5 to guard "
            "the singleton reviewing→closing transition."
        ),
    )
    usi_p.add_argument("story_id", help="Story ID")
    usi_p.add_argument("--expected", required=True, help="Required current status")
    usi_p.add_argument(
        "--new", required=True, choices=_STATUS_CHOICES, help="New status"
    )

    usb_p = sub.add_parser("update-story-branch", help="Set a story's branch name")
    usb_p.add_argument("story_id", help="Story ID")
    usb_p.add_argument("branch_name", help="Branch name to record")

    gsb_p = sub.add_parser(
        "get-story-branch",
        help="Print a story's recorded branch_name (empty if unset/missing)",
    )
    gsb_p.add_argument("story_id", help="Story ID")

    gs_p = sub.add_parser(
        "get-story",
        help="Print one story as JSON (exits non-zero if id is unknown)",
    )
    gs_p.add_argument("story_id", help="Story ID")

    vd_p = sub.add_parser(
        "validate-domain",
        help=(
            "Diff a story branch's actual changes (since --base) against "
            "its declared file_domain; exit non-zero on drift"
        ),
    )
    vd_p.add_argument("story_id", help="Story ID to validate")
    vd_p.add_argument(
        "--base",
        required=True,
        help="Base ref to diff against (typically the sprint branch)",
    )
    vd_p.add_argument(
        "--cwd",
        type=Path,
        default=Path("."),
        help="Working directory for git operations (default: current dir)",
    )

    ftd_p = sub.add_parser(
        "find-transitive-dependents",
        help=(
            "Print space-separated in-motion (in-progress, reviewing, or "
            "closing) story ids that depend (transitively) on the given "
            "story; powers cascade-deferral"
        ),
    )
    ftd_p.add_argument("story_id", help="Story ID to walk dependents of")

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "has-active": _cmd_has_active,
        "is-complete": _cmd_is_complete,
        "next-in-progress": _cmd_next_in_progress,
        "next-scheduled": _cmd_next_scheduled,
        "scheduled-overlap": _cmd_scheduled_overlap,
        "count": _cmd_count,
        "count-status": _cmd_count_status,
        "next-id": _cmd_next_id,
        "velocity": _cmd_velocity,
        "render": _cmd_render,
        "render-stories": _cmd_render_stories,
        "list-stories": _cmd_list_stories,
        "create": _cmd_create,
        "add-story": _cmd_add_story,
        "edit-story": _cmd_edit_story,
        "update-story": _cmd_update_story,
        "update-story-if": _cmd_update_story_if,
        "update-story-branch": _cmd_update_story_branch,
        "get-story-branch": _cmd_get_story_branch,
        "get-story": _cmd_get_story,
        "find-transitive-dependents": _cmd_find_transitive_dependents,
        "validate-domain": _cmd_validate_domain,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
