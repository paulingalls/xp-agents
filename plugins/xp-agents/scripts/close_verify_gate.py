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

import identity
import sprint_store
import verify_acceptance
import verify_deferred
import verify_paths


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
            status, failing = verify_acceptance._last_verify(
                smm_dir, sprint["sprint_id"]
            )
            if status == verify_acceptance.VERIFY_STATUS_RED and not args.force_verify:
                items = ", ".join(
                    f"{r.get('story', '?')} {r.get('command', '')}" for r in failing
                )
                return (
                    "merge refused: sprint acceptance is red: "
                    f"{items}; fix and re-run /xp-sprint-review, or "
                    "/xp-sprint-close --force-close <reason>"
                )
            return None

    return None
