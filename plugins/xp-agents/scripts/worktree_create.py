#!/usr/bin/env python3
"""WorktreeCreate hook: create worktree from current branch, not origin/HEAD.

When working on a non-default branch (e.g., feature/xp-teammate), worktrees
should branch from the current branch instead of origin/HEAD. This hook
determines the correct base ref and creates the worktree accordingly.

Platform input (stdin JSON):
  session_id, transcript_path, cwd, hook_event_name, name

The hook must:
1. Generate the worktree path (under .claude/worktrees/)
2. Create a branch from the current branch (not origin/HEAD)
3. Print ONLY the worktree path on stdout (no other output)
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common


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


def _get_repo_root(cwd: str) -> str:
    """Get git repo root directory."""
    return subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        cwd=cwd,
        stderr=subprocess.DEVNULL,
    ).strip()


def run(input_data: dict) -> str:
    """Create worktree with correct branch base. Returns worktree path.

    Platform input fields:
    - name: worktree name (used for branch and directory)
    - cwd: current working directory of the parent session
    """
    cwd = input_data.get("cwd", ".")
    name = input_data.get("name", "")

    if not name:
        import uuid

        name = f"worktree-{uuid.uuid4().hex[:8]}"
        print(
            f"WorktreeCreate: no name, generated: {name}",
            file=sys.stderr,
        )

    # Generate worktree path under .claude/worktrees/ in repo root
    repo_root = _get_repo_root(cwd)
    worktree_dir = Path(repo_root) / ".claude" / "worktrees"
    worktree_dir.mkdir(parents=True, exist_ok=True)
    worktree_path = str(worktree_dir / name)

    # Branch from current branch if it differs from default
    branch = f"worktree-{name}"
    current = _common.get_current_branch(cwd)
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
