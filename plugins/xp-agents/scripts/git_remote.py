#!/usr/bin/env python3
"""Shared git-remote helper (has_remote)."""

import subprocess


def has_remote(cwd: str) -> bool:
    result = subprocess.run(["git", "remote"], cwd=cwd, capture_output=True, text=True)
    return bool(result.stdout.strip())
