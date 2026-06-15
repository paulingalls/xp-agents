#!/usr/bin/env python3
"""Sprint and planning document state detection helpers.

Delegates sprint checks to sprint_store.py (JSON format).
Used by session_start.py, pre_tool_write.py, and gates for
deterministic state detection.
"""

from pathlib import Path


def has_active_stories(smm_dir: Path) -> bool:
    """True if sprint has ready or in-progress stories."""
    from sprint_store import has_active_stories as _fn

    return _fn(smm_dir)


def has_in_progress_stories(smm_dir: Path) -> bool:
    """True if sprint has in-progress stories."""
    from sprint_store import has_in_progress_stories as _fn

    return _fn(smm_dir)


def has_reviewing_stories(smm_dir: Path) -> bool:
    """True if sprint has reviewing stories."""
    from sprint_store import has_reviewing_stories as _fn

    return _fn(smm_dir)


def has_closing_stories(smm_dir: Path) -> bool:
    """True if sprint has closing stories."""
    from sprint_store import has_closing_stories as _fn

    return _fn(smm_dir)


def has_in_motion_stories(smm_dir: Path) -> bool:
    """True if sprint has in-motion (in-progress, reviewing, or closing) stories."""
    from sprint_store import has_in_motion_stories as _fn

    return _fn(smm_dir)


def in_progress_is_teammate(smm_dir: Path) -> bool:
    """True iff an in-progress story has execution_mode == 'teammate'."""
    from sprint_store import in_progress_is_teammate as _fn

    return _fn(smm_dir)


def read_sprint_content(smm_dir: Path) -> dict | None:
    """Load sprint data from sprint.json. Returns None if missing."""
    from sprint_store import load_sprint

    return load_sprint(smm_dir)


def has_ready_stories(smm_dir: Path) -> bool:
    """True if sprint has ready stories."""
    from sprint_store import has_ready_stories as _fn

    return _fn(smm_dir)


def is_sprint_complete(smm_dir: Path) -> bool:
    """True when no ready or in-progress stories remain."""
    from sprint_store import is_complete

    return is_complete(smm_dir)


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
    """Check if system_context.json exists in SMM dir (not a symlink)."""
    from system_context_store import system_context_exists as _store_fn

    return _store_fn(smm_dir)
