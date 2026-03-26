#!/usr/bin/env python3
"""Shared commit utilities for pre and post Bash hooks.

Provides commit detection, parsing, and file enumeration used by both
PreToolUse:Bash (gate) and PostToolUse:Bash (bookkeeping).
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import security

REVIEW_CYCLE_THRESHOLD: int = 3


def parse_commit_message(tool_response: str) -> str | None:
    """Extract first line of commit message from git output."""
    match = re.search(r"\[[\w/.-]+\s+\w+\]\s+(.+)", tool_response)
    if match:
        return match.group(1).strip()
    return None


def get_committed_files(cwd: str) -> list[str]:
    """Get list of files changed in the last commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--name-only"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    return []


def get_head_commit_hash(cwd: str) -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    return None


def get_code_files_for_review(
    cwd: str, last_review_commit: str, command: str = ""
) -> list[str]:
    """Get deduplicated code files changed since last review + staged.

    Combines git diff --cached --name-only with git diff --name-only
    {last_review_commit}..HEAD (if a prior commit exists). Filters
    through security.is_code_file(). Returns empty list on git failure.
    """
    diff_commands: list[list[str]] = [["git", "diff", "--cached", "--name-only"]]

    if last_review_commit:
        diff_commands.append(
            ["git", "diff", "--name-only", f"{last_review_commit}..HEAD"]
        )

    # If the command includes 'git add' or 'git commit -a', also check
    # unstaged tracked changes (same pattern as security.has_staged_code_files)
    if re.search(r"\bgit\s+add\b", command) or re.search(
        r"\bgit\s+commit\s+-a", command
    ):
        diff_commands.append(["git", "diff", "--name-only"])

    all_files: set[str] = set()
    try:
        for cmd in diff_commands:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=cwd,
            )
            if result.returncode != 0:
                return []
            for f in result.stdout.strip().splitlines():
                f = f.strip()
                if f:
                    all_files.add(f)
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []

    return [f for f in sorted(all_files) if security.is_code_file(f)]
