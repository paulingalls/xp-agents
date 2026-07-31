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

# The 7 structural-mutation handlers (create, add-story, update-story,
# update-story-if, edit-story, build-capstone, update-story-branch) live in
# sprint_cli_mutate.py — split out in sprint-108 M1 to keep both modules
# under the 500-line cap (decision d027fe5c9066). They are wired into the
# argparse dispatch table in main() exactly as before. One-directional
# import: sprint_cli -> sprint_cli_mutate -> sprint_store.
from sprint_cli_mutate import (
    _cmd_add_story,
    _cmd_archive,
    _cmd_build_capstone,
    _cmd_create,
    _cmd_edit_story,
    _cmd_set_executor,
    _cmd_update_story,
    _cmd_update_story_branch,
    _cmd_update_story_if,
)

# The read-only query handlers (render, render-stories, count, count-status,
# next-id, velocity, list-stories, validate-domain) live in
# sprint_cli_query.py — split out to keep both modules under the 500-line
# cap. Re-exported here by identity so main()'s dispatch table and any
# `mock.patch("...sprint_cli.X")` sites keep working unchanged.
from sprint_cli_query import (
    _cmd_count,
    _cmd_count_status,
    _cmd_list_carryover,
    _cmd_list_stories,
    _cmd_next_id,
    _cmd_render,
    _cmd_render_stories,
    _cmd_validate_domain,
    _cmd_velocity,
)
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


def _cmd_ready_frontier(args: argparse.Namespace) -> int:
    report = store.ready_frontier_report(
        args.smm_dir, treat_as_done=set(args.treat_as_done)
    )
    print(json.dumps(report))
    return 0


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
            "Repeatable. Lets a promotion query surface a next story whose "
            "dep is the just-closed story (still 'closing' at promotion "
            "time, not yet 'done')."
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
    rf_p = sub.add_parser(
        "ready-frontier",
        help=(
            "Print JSON {frontier, parallelizable, overlap}: dep-satisfied "
            "scheduled stories + whether they are a disjoint-domain fan-out "
            "(>=2) + the collision/glob overlap detail. "
            "Consumed by the /xp-schedule preload. Exit 0 always."
        ),
    )
    rf_p.add_argument(
        "--treat-as-done",
        action="append",
        default=[],
        metavar="STORY_ID",
        help="Same as next-scheduled: treat these ids as done for dep checks.",
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

    bc_p = sub.add_parser(
        "build-capstone",
        help=(
            "Print a deterministic capstone story as JSON (pipe into "
            "add-story). Pure — does not read or write the sprint."
        ),
    )
    bc_p.add_argument("--milestone", required=True, help="Milestone name")
    bc_p.add_argument(
        "--surfaces",
        default="",
        help="Comma-separated touched surface names (one object AC each)",
    )
    bc_p.add_argument(
        "--depends-on",
        default="",
        help="Comma-separated sibling story ids the capstone depends on",
    )
    bc_p.add_argument("--story-id", required=True, help="Capstone story id")
    bc_p.add_argument(
        "--milestone-ref", default="", help="milestone_ref string for the story"
    )
    bc_p.add_argument(
        "--harness",
        default=None,
        help=(
            "acceptance_execution type; omit to resolve from the capstone's "
            "own --surfaces in system_context"
        ),
    )

    edit_p = sub.add_parser("edit-story", help="Edit story fields from stdin JSON")
    edit_p.add_argument("story_id", help="Story ID to edit")

    setx_p = sub.add_parser(
        "set-executor",
        help="Persist executor_model + executor_effort as value-or-null",
    )
    setx_p.add_argument("story_id", help="Story ID to set")
    setx_p.add_argument(
        "--model",
        default=None,
        help="Decided tier; provided-empty -> null; omitted -> leave unchanged",
    )
    setx_p.add_argument(
        "--effort",
        default=None,
        help="Decided effort; provided-empty -> null; omitted -> leave unchanged",
    )

    update_p = sub.add_parser("update-story", help="Update story status")
    update_p.add_argument("story_id", help="Story ID")
    update_p.add_argument(
        "status",
        choices=_STATUS_CHOICES,
        help="New status",
    )
    update_p.add_argument(
        "--force-unmerged",
        metavar="REASON",
        help=(
            "Mark `done` despite an unverified merge (the pre-commit Bash gate "
            "otherwise refuses). REASON is required and non-empty: the bypass is "
            "recorded as a debt event, so it can never be silent."
        ),
    )
    update_p.add_argument(
        "--cwd",
        type=Path,
        default=Path("."),
        help="Working directory for git operations (default: current dir)",
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
    usi_p.add_argument(
        "--force-unmerged",
        metavar="REASON",
        help=(
            "Mark `done` despite an unverified merge (the pre-commit Bash gate "
            "otherwise refuses). REASON is required and non-empty: the bypass is "
            "recorded as a debt event, so it can never be silent."
        ),
    )
    usi_p.add_argument(
        "--cwd",
        type=Path,
        default=Path("."),
        help="Working directory for git operations (default: current dir)",
    )

    usb_p = sub.add_parser("update-story-branch", help="Set a story's branch name")
    usb_p.add_argument("story_id", help="Story ID")
    usb_p.add_argument(
        "branch_name",
        help="Branch name to record; '' clears it (releases a stale file_domain claim)",
    )

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

    sub.add_parser("archive", help="Archive sprint to sprints/ folder")
    sub.add_parser(
        "list-carryover",
        help="Deferred stories to carry into the next sprint; falls back to "
        "the newest archived sprint when sprint.json has been archived away",
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
        "ready-frontier": _cmd_ready_frontier,
        "count": _cmd_count,
        "count-status": _cmd_count_status,
        "next-id": _cmd_next_id,
        "velocity": _cmd_velocity,
        "render": _cmd_render,
        "render-stories": _cmd_render_stories,
        "list-stories": _cmd_list_stories,
        "create": _cmd_create,
        "add-story": _cmd_add_story,
        "build-capstone": _cmd_build_capstone,
        "edit-story": _cmd_edit_story,
        "set-executor": _cmd_set_executor,
        "update-story": _cmd_update_story,
        "update-story-if": _cmd_update_story_if,
        "update-story-branch": _cmd_update_story_branch,
        "get-story-branch": _cmd_get_story_branch,
        "get-story": _cmd_get_story,
        "find-transitive-dependents": _cmd_find_transitive_dependents,
        "validate-domain": _cmd_validate_domain,
        "archive": _cmd_archive,
        "list-carryover": _cmd_list_carryover,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
