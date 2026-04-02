#!/usr/bin/env python3
"""Sprint and product spec state detection helpers.

Pure functions for checking sprint.md and product_spec.md state.
Used by session_start.py and kickoff_done.py for deterministic
sprint state detection (M8a).
"""

import re
from pathlib import Path

_ACTIVE_RE = re.compile(r"\*\*Status:\*\*\s*(ready|in-progress)")
_IN_PROGRESS_RE = re.compile(r"\*\*Status:\*\*\s*in-progress")


def has_active_stories(sprint_content: str) -> bool:
    """Return True if sprint content contains ready or in-progress stories."""
    return bool(_ACTIVE_RE.search(sprint_content))


def has_in_progress_stories(sprint_content: str) -> bool:
    """Return True if sprint content contains in-progress stories."""
    return bool(_IN_PROGRESS_RE.search(sprint_content))


def read_sprint_content(smm_dir: Path) -> str | None:
    """Read sprint.md from SMM dir. Returns None if missing or symlink."""
    path = smm_dir / "sprint.md"
    if path.is_symlink():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


def product_spec_exists(smm_dir: Path) -> bool:
    """Check if product_spec.md exists in SMM dir (not a symlink)."""
    path = smm_dir / "product_spec.md"
    return path.exists() and not path.is_symlink()
