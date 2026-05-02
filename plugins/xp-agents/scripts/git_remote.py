#!/usr/bin/env python3
"""Shared git-remote helpers (has_remote, push_branch)."""

import subprocess
import sys


def has_remote(cwd: str) -> bool:
    result = subprocess.run(["git", "remote"], cwd=cwd, capture_output=True, text=True)
    return bool(result.stdout.strip())


def push_branch(cwd: str, branch: str) -> bool:
    """Push `branch` to origin with upstream tracking.

    Returns True on success OR when no remote is configured (silent skip
    — no remote is not an error). Returns False on push failure and
    relays git's stderr so the caller can surface the cause.
    """
    if not has_remote(cwd):
        return True
    r = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return False
    return True
