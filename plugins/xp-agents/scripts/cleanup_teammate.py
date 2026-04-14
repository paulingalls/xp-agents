#!/usr/bin/env python3
"""Clean up a CLI teammate's worktree, branch, markers, and report.

Verifies the teammate's branch is fully merged before removing anything.
Called by /xp-accept after story acceptance.

Usage:
    python3 cleanup_teammate.py \
        --name teammate-story-001 \
        --smm-dir /path/to/smm
"""

import argparse
import contextlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers


def verify_merged(name: str, cwd: str) -> bool:
    """Check if a branch is fully merged into the current branch."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", name, "HEAD"],
        cwd=cwd,
        capture_output=True,
    )
    return result.returncode == 0


def cleanup(name: str, cwd: str, smm_dir: Path) -> None:
    """Remove worktree, branch, agent markers, and report file."""
    _common.remove_worktree(name, cwd)
    markers.cleanup_agent_markers(smm_dir, name)
    report = _common.teammate_report_path(smm_dir, name)
    with contextlib.suppress(OSError):
        report.unlink()


def main(argv: list[str] | None = None) -> int:
    """Parse args, verify merge, and clean up."""
    parser = argparse.ArgumentParser(description="Clean up a CLI teammate")
    parser.add_argument("--name", required=True)
    parser.add_argument("--smm-dir", required=True)
    args = parser.parse_args(argv)

    cwd = _common.resolve_git_root(os.getcwd())
    if not cwd:
        print("Not in a git repository.", file=sys.stderr)
        return 1

    if not verify_merged(args.name, cwd):
        print(
            f"Branch {args.name} has unmerged commits. Merge before cleanup.",
            file=sys.stderr,
        )
        return 1

    cleanup(args.name, cwd, Path(args.smm_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
