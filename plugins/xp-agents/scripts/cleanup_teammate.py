#!/usr/bin/env python3
"""Clean up a CLI teammate's worktree, branch, markers, and report.

Verifies the teammate's branch is fully merged before removing anything.
Called by /xp-story-close per closed teammate story (per-story symmetry).

`--name` is the worktree DIR name (e.g. ``worktree-story-001``); the actual
branch (e.g. ``<user>/story-001-<slug>``) is derived from the worktree's
checked-out HEAD so the merge check matches the real ref.

Usage:
    python3 cleanup_teammate.py \
        --name worktree-story-001 \
        --smm-dir /path/to/smm \
        [--cwd /path/to/repo]   # defaults to os.getcwd()
"""

import argparse
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branch_lifecycle
import branch_resolution
import identity
import markers
import worktree


def verify_merged(branch: str, cwd: str, base: str) -> bool:
    """Check if a branch is fully merged into `base`."""
    return branch_lifecycle.is_merged_into(cwd, branch, base)


def cleanup(name: str, cwd: str, smm_dir: Path, base: str) -> None:
    """Remove worktree, branch, agent markers, and report file."""
    worktree.remove_worktree(name, cwd, merge_target=base)
    markers.cleanup_agent_markers(smm_dir, name)
    report = worktree.teammate_report_path(smm_dir, name)
    with contextlib.suppress(OSError):
        report.unlink()
    assignment = worktree.story_assignment_path(smm_dir, name)
    with contextlib.suppress(OSError):
        assignment.unlink()


def main(argv: list[str] | None = None) -> int:
    """Parse args, verify merge, and clean up."""
    parser = argparse.ArgumentParser(description="Clean up a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", default=None)
    args = parser.parse_args(argv)

    cwd = worktree.resolve_git_root(args.cwd or os.getcwd())
    if not cwd:
        print("Not in a git repository.", file=sys.stderr)
        return 1

    wt_path = worktree.worktree_path(args.name, cwd)
    derived = identity.get_current_branch(str(wt_path))
    branch = derived or args.name

    if not branch_resolution.branch_exists(cwd, branch):
        # Fallback to --name hit a non-existent ref. Distinguish from
        # "exists but unmerged" so the operator knows the right next step.
        suffix = "" if derived else " (worktree gone — fell back to --name)"
        print(
            f"Branch {branch} not found.{suffix}",
            file=sys.stderr,
        )
        return 1

    try:
        base = branch_resolution.get_story_base_branch_required(Path(args.smm_dir), cwd)
    except (ValueError, OSError) as e:
        # OSError as well as ValueError: the underlying sprint/system_context reads
        # (load_sprint, get_branching_stage) raise OSError on an unreadable or
        # symlinked sprint.json. Catching only ValueError let that crash the close
        # with a traceback instead of the intended clean refusal (return 1).
        print(str(e), file=sys.stderr)
        return 1

    if not verify_merged(branch, cwd, base):
        print(
            f"Branch {branch} has unmerged commits. Merge before cleanup.",
            file=sys.stderr,
        )
        return 1

    cleanup(args.name, cwd, Path(args.smm_dir), base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
