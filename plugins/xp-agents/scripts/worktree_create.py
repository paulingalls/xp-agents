#!/usr/bin/env python3
"""WorktreeCreate hook: create worktree from current branch, not origin/HEAD.

When working on a non-default branch (e.g., v2), worktrees should branch
from the current branch instead of origin/HEAD. This hook determines the
correct base ref and creates the worktree accordingly.

Stdout must contain ONLY the worktree path — any extra output causes
Claude Code to hang.
"""

import json
import subprocess
import sys


def _get_current_branch(cwd: str) -> str:
    """Get current branch name. Returns empty string on detached HEAD."""
    try:
        return subprocess.check_output(
            ["git", "branch", "--show-current"],
            text=True,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return ""


def _get_default_branch(cwd: str) -> str:
    """Get default branch from origin/HEAD. Returns empty string if no remote."""
    try:
        ref = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            text=True,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
        ).strip()
        return ref.removeprefix("origin/")
    except subprocess.CalledProcessError:
        return ""


def run(input_data: dict) -> str:
    """Create worktree with correct branch base. Returns worktree path."""
    worktree_path = input_data["worktree_path"]
    branch = input_data["branch"]
    cwd = input_data.get("cwd", ".")

    current = _get_current_branch(cwd)
    default = _get_default_branch(cwd)

    cmd = ["git", "worktree", "add", "-b", branch, worktree_path]
    if current and default and current != default:
        cmd.append(current)

    subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )
    return worktree_path


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    print(run(input_data))
    sys.exit(0)
