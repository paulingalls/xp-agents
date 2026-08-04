#!/usr/bin/env python3
"""Deterministic close-gate backstop for close_common.py's `merge`.

Extracted from close_common.py to keep that module under the 500-line
target. The single public entry point is ``verify_gate_block(args)``,
called first by ``cmd_merge`` before the merge runs; it re-derives the
gate signal and returns a refusal reason (or None to proceed).
"""

import argparse
import sys
from pathlib import Path

# Resolve sibling/smm modules without modifying caller sys.path.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import identity
import sprint_store

# verify_acceptance_record is the READ side of the verify event, not the runner:
# this gate never runs an acceptance command, and importing `verify_acceptance`
# for two reader names would pull its whole subprocess half in with them.
import verify_acceptance_record
import verify_deferred
import verify_paths
from event_schema import VERIFY_STATUS_RED


def review_clean_block(review_cwd: str) -> str:
    """Refusal message when the post-review target worktree is dirty, else "".

    Reviewer fixes applied during the close review (xp-story-close Step 4.5b)
    land in the teammate worktree; if left uncommitted, the merge (whose branch
    tip lacks them) followed by Step 7b worktree removal would silently drop
    them. This is a second clean-check AFTER the review — Step 1 preflight only
    checks BEFORE it. Empty *review_cwd* (solo close, or the arg omitted) skips
    the check; solo working-tree edits persist in the checkout rather than being
    deleted, so only the teammate path needs it.
    """
    if not review_cwd:
        return ""
    # A missing/invalid target (misdetected or already-removed path) holds no
    # reviewer fix to protect, and `is_worktree_clean` would report it "dirty"
    # (git status errors) — a misleading, un-clearable refusal that's worse than
    # skipping. Only a real, checkable worktree gets the clean gate.
    if not branching.is_git_worktree(review_cwd):
        return ""
    if branching.is_worktree_clean(review_cwd):
        return ""
    return (
        f"merge refused: review target {review_cwd} has uncommitted changes "
        "(likely a reviewer fix from the close review that worktree cleanup "
        "would otherwise discard). Either commit the fix — "
        f"git -C {review_cwd} add -A && git -C {review_cwd} commit -m ... "
        "(add -A also stages NEW files a plain commit -am would miss) — or, if "
        f"it is unrelated scratch, clear it (git -C {review_cwd} stash -u), "
        "then re-run."
    )


def verify_gate_block(args: argparse.Namespace) -> str | None:
    """Deterministic close-gate backstop: re-derive the gate signal and return
    a refusal reason, or None to proceed.

    Defends against an LLM that skips the SKILL prose gate. Both gates fail
    CLOSED on their own signal; on git/SMM errors the touch gate fails OPEN
    (matching verify_paths' established contract — an unreadable range can't
    block a legitimate merge, and a broken ref would fail the merge anyway).

    Inert when no --verify-gate (plan/free close). Refuses (rather than
    silently no-op'ing) when --verify-gate is set without --smm-dir: a
    misconfigured invocation must not invisibly disable the backstop.
    """
    if not args.verify_gate:
        return None
    if not args.smm_dir:
        return "merge refused: --verify-gate requires --smm-dir"
    smm_dir = Path(args.smm_dir)

    match args.verify_gate:
        case "touch":
            # Self-derived from sprint.json + git: refuse when the story's
            # declared acceptance-test paths are untouched on target..source
            # and no [verify-deferred] commit defers them.
            story_id = identity.extract_story_id(args.source)
            if not story_id:
                return None
            try:
                story = sprint_store.get_story(smm_dir, story_id)
            except sprint_store.SprintCorruptError as exc:
                return f"merge refused: sprint.json is corrupt or schema-invalid: {exc}"
            except (ValueError, OSError):
                return None  # missing sprint/story (or symlink) → fail open
            paths = verify_paths.extract_verify_paths(story)
            if not paths:
                return None
            try:
                untouched = verify_paths.untouched_verify_paths(
                    paths, args.cwd, base=args.target, head=args.source
                )
            except ValueError:
                return None  # fail open: unreadable range can't block
            if untouched and not verify_deferred.branch_has_verify_deferred(
                args.cwd, args.target, head=args.source
            ):
                return (
                    f"merge refused: no commit on {args.target}..{args.source} "
                    f"touched {untouched}; add a touching commit or commit with "
                    "[verify-deferred] <reason>"
                )
            return None

        case "acceptance":
            # Reads the last sprint-verify event (cwd-independent): refuse on
            # red unless the SKILL passed --force-verify (the --force-close path,
            # which already recorded the bypass as debt).
            try:
                sprint = sprint_store.load_sprint(smm_dir)
            except sprint_store.SprintCorruptError as exc:
                return f"merge refused: sprint.json is corrupt or schema-invalid: {exc}"
            except OSError:
                return None  # symlinked sprint path → fail open (matches touch gate)
            if sprint is None:
                return None
            status, failing, skipped = verify_acceptance_record._last_verify(
                smm_dir, sprint["sprint_id"]
            )
            if status == VERIFY_STATUS_RED and not args.force_verify:
                # Shared with the CLI status printer: a sprint red purely
                # because the batch budget SKIPPED items would otherwise refuse
                # with an empty list — right to refuse, silent about why.
                items = ", ".join(
                    verify_acceptance_record.unverified_items(failing, skipped)
                )
                return (
                    "merge refused: sprint acceptance is red: "
                    f"{items}; fix and re-run /xp-sprint-review, or "
                    "/xp-sprint-close --force-close <reason>"
                )
            return None

    return None
