#!/usr/bin/env python3
"""Agent identity resolution utilities.

Resolves agent identity from hook input, worktree CWD path, or defaults.
Detects CLI teammates by worktree directory prefix.
"""

import subprocess

_WORKTREE_PATH_MARKER = "/.claude/worktrees/"


def get_current_branch(cwd: str) -> str:
    """Get current git branch name, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def extract_worktree_name(cwd: str) -> str | None:
    """Extract worktree directory name from cwd, or None if not in worktree."""
    idx = cwd.find(_WORKTREE_PATH_MARKER)
    if idx < 0:
        return None
    tail = cwd[idx + len(_WORKTREE_PATH_MARKER) :]
    return tail.split("/")[0]


def is_worktree_teammate(input_data: dict) -> bool:
    """Detect CLI teammates by worktree cwd path with teammate- prefix."""
    name = extract_worktree_name(input_data.get("cwd", ""))
    return name.startswith("teammate-") if name else False


def resolve_agent_id(input_data: dict) -> str:
    """Resolve agent_id from hook input, worktree path, or default."""
    agent_id = input_data.get("agent_id", "")
    if agent_id:
        return agent_id
    return extract_worktree_name(input_data.get("cwd", "")) or "main"
