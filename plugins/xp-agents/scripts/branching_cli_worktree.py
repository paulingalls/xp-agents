#!/usr/bin/env python3
"""CLI subcommand handlers for teammate-worktree resolution.

Extracted from branching_cli.py (which stayed the thin dispatch layer) to
keep both files under the line cap. These handlers resolve teammate
worktree paths/branches for downstream SKILL.md consumers — /xp-story-close
and /xp-quality-review in particular.
"""

import argparse
import sys
from pathlib import Path

import worktree


def _cmd_list_teammate_worktree_paths(args: argparse.Namespace) -> int:
    """Print ``story-id\\tabs-path`` per live teammate. Empty stdout = none.

    Tab-delimited: worktree paths can contain spaces on macOS
    (``/Users/foo bar/...``); tab guarantees consumers can split on a
    single byte that cannot legally appear in either field.
    """
    for story_id, wt_path in worktree.list_live_teammate_worktree_paths(args.cwd):
        print(f"{story_id}\t{wt_path}")
    return 0


def _cmd_find_teammate_worktree(args: argparse.Namespace) -> int:
    """Print teammate worktree NAME for a story id, empty if none live.

    Always exits 0 — empty stdout signals "no live teammate worktree"
    (solo mode, or already cleaned up) so SKILL.md callers can gate on
    non-empty without distinguishing error vs no-match.
    """
    print(worktree.find_teammate_worktree_for_story(args.story_id, args.cwd) or "")
    return 0


def _cmd_find_closing_teammate_worktree(args: argparse.Namespace) -> int:
    """Print ``<abs-path>\\t<branch>`` for the worktree of the in-reviewing story.

    Implicit-derivation discovery for /xp-story-close: pairs the live
    teammate worktree with its sprint.json story status; prints exactly
    when one worktree's story is `reviewing`. Under close-then-done
    semantics, /xp-story-close runs while the story is still in
    `reviewing` (mark-done is the FINAL step after merge). Empty stdout
    = no match (solo, or no teammate finished). Non-zero exit + stderr
    on multi-match — that signals broken /xp-accept iteration; fail loud
    rather than guess which worktree to close.

    Tab-delimited: worktree paths can contain spaces on macOS; the
    prior space-delimited emit forced bash consumers to lean on the
    implicit "git refs cannot contain spaces" invariant via
    ``${var% *}``/``${var##* }``. That invariant happens to hold but is
    not self-documenting — tab makes the contract explicit.
    """
    try:
        result = worktree.find_closing_teammate_worktree(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if result is not None:
        abs_path, branch = result
        print(f"{abs_path}\t{branch}")
    return 0


def _cmd_resolve_review_worktree(args: argparse.Namespace) -> int:
    """Print ``<abs-path>\\t<branch>`` for /xp-quality-review's target worktree.

    Invoker-identity precedence: the invoker's OWN teammate worktree wins over
    the closing-story scan (fixes the parallel-teammate CWD-misdetect). Empty
    stdout = orchestrator with no closing story. Non-zero exit + stderr
    propagates find_closing's multi-closing ValueError (fail loud).
    """
    try:
        result = worktree.resolve_review_worktree(Path(args.smm_dir), args.cwd)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if result is not None:
        abs_path, branch = result
        print(f"{abs_path}\t{branch}")
    return 0
