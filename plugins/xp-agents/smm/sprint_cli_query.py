#!/usr/bin/env python3
"""Read-only query subcommand handlers for sprint_cli.py.

Split out of sprint_cli.py to keep both modules under the 500-line cap
(same split-shim convention used for sprint_cli_mutate.py and
event_metadata.py: sprint_cli.py re-exports every name here by identity,
so callers and `mock.patch("...sprint_cli.X")` sites keep working with
zero edits). One-directional import: sprint_cli -> sprint_cli_query ->
sprint_store/sprint_render/triage.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sprint_render as render
import sprint_store as store
import triage
from sprint_schema import VALID_STORY_STATUSES

# Sorted to keep output stable across runs (frozenset iteration order is
# not guaranteed). Mirrors sprint_cli.py's own _STATUS_CHOICES — kept as
# a separate module-local copy here (not imported back from sprint_cli)
# to avoid a circular import, since sprint_cli imports this module.
_STATUS_CHOICES = sorted(VALID_STORY_STATUSES)


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
    # Shared fixtures, drift-guard configs, and other plumbing files
    # often live outside a story's owned-code file_domain because
    # they're infrastructure, not story scope. K=1 default avoids false
    # positives on this common pattern while still surfacing multi-file
    # drift that signals scope creep. Set XP_FILE_DOMAIN_DRIFT_TOLERANCE=0
    # to restore strict matching for stories that need a tighter
    # contract. Read per-invocation so per-sprint or per-story overrides
    # can slot in without reshaping callers.
    tolerance = int(os.getenv("XP_FILE_DOMAIN_DRIFT_TOLERANCE", "1"))
    if len(drift) > tolerance:
        print(
            f"drift: {len(drift)} file(s) outside declared file_domain: "
            + " ".join(drift),
            file=sys.stderr,
        )
        return 1
    if drift:
        # Within tolerance — still exit 0, but surface the absorbed
        # paths so retros and quality-review can see what slipped past
        # the K-budget. Prefix-matches the over-tolerance line for
        # grep-friendliness. Stdout reports "absorbed" rather than
        # "clean" so callers parsing stdout get an honest signal.
        print(
            f"drift (within K={tolerance}): {len(drift)} file(s): " + " ".join(drift),
            file=sys.stderr,
        )
        print(
            f"absorbed: {len(actual)} file(s), {len(drift)} drift within K={tolerance}"
        )
        return 0

    print(f"clean: {len(actual)} file(s) match declared domain")
    return 0
