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
3. Run the project's declared worktree_bootstrap command in it, if any
   (see worktree_bootstrap.run_bootstrap) — SMM-less projects skip this
4. Print ONLY the worktree path on stdout (no other output)
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import identity
import worktree
import worktree_bootstrap


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

    wt = worktree.worktree_path(name, cwd)
    wt.parent.mkdir(parents=True, exist_ok=True)
    worktree_path = str(wt)

    # Branch from current branch if it differs from default
    branch = f"worktree-{name}"
    current = identity.get_current_branch(cwd)
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

    smm_dir = _common.resolve_smm_dir()
    if smm_dir is not None:
        worktree_bootstrap.run_bootstrap(worktree_path, smm_dir)

    return worktree_path


if __name__ == "__main__":
    input_data = json.load(sys.stdin)
    print(run(input_data))
    sys.exit(0)
