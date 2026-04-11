#!/usr/bin/env python3
"""Sprint and planning document state detection helpers.

Pure functions for checking sprint.md, execution_plan.json, and
system_context.md state. Used by session_start.py and kickoff_done.py
for deterministic state detection.
"""

import re
from pathlib import Path

_ACTIVE_RE = re.compile(r"\*\*Status:\*\*\s*(ready|in-progress)")
_IN_PROGRESS_RE = re.compile(r"\*\*Status:\*\*\s*in-progress")
_READY_RE = re.compile(r"\*\*Status:\*\*\s*ready")


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


def has_ready_stories(sprint_content: str) -> bool:
    """Return True if sprint content contains ready stories."""
    return bool(_READY_RE.search(sprint_content))


def is_sprint_complete(sprint_content: str) -> bool:
    """Return True when no ready or in-progress stories remain."""
    return not _ACTIVE_RE.search(sprint_content)


def _safe_file_exists(smm_dir: Path, filename: str) -> bool:
    """Check if a file exists in SMM dir and is not a symlink."""
    path = smm_dir / filename
    return path.exists() and not path.is_symlink()


def execution_plan_exists(smm_dir: Path) -> bool:
    """Check if execution_plan.json exists in SMM dir (not a symlink)."""
    return _safe_file_exists(smm_dir, "execution_plan.json")


def has_remaining_work(smm_dir: Path) -> bool:
    """True if execution plan has planned or in-progress milestones."""
    # Lazy import: execution_plan_store lives in smm/, not scripts/.
    # Callers (session_start.py) set up sys.path before importing us.
    from execution_plan_store import has_remaining_work as _store_fn

    return _store_fn(smm_dir)


def system_context_exists(smm_dir: Path) -> bool:
    """Check if system_context.md exists in SMM dir (not a symlink)."""
    return _safe_file_exists(smm_dir, "system_context.md")
