#!/usr/bin/env python3
"""Status-check helpers for sprint.json.

Extracted from sprint_store.py once that module crossed 500 lines.
sprint_store re-exports every name defined here so existing call sites
(`from sprint_store import has_active_stories`) keep working.

`load_sprint` is imported lazily inside each function so this module can
import cleanly without a cycle when sprint_store re-exports back.
"""

from itertools import combinations
from pathlib import Path

from sprint_schema import ACTIVE_STORY_STATUSES, IN_MOTION_STORY_STATUSES
from triage import extract_file_domain_paths


def has_active_stories(smm_dir: Path) -> bool:
    """True if sprint has ready or in-progress stories."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_active_stories_data(sprint)


def has_active_stories_data(data: dict) -> bool:
    """True if sprint dict has ready or in-progress stories."""
    return any(s["status"] in ACTIVE_STORY_STATUSES for s in data["stories"])


def has_stories_with_status(smm_dir: Path, status: str) -> bool:
    """True if sprint has any story matching `status`."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_stories_with_status_data(sprint, status)


def has_stories_with_status_data(data: dict, status: str) -> bool:
    """True if sprint dict has any story matching `status`.

    Sibling to has_stories_with_status for callers that already hold
    the loaded sprint dict.
    """
    return any(s["status"] == status for s in data["stories"])


def has_in_progress_stories(smm_dir: Path) -> bool:
    """True if sprint has in-progress stories."""
    return has_stories_with_status(smm_dir, "in-progress")


def has_in_progress_stories_data(data: dict) -> bool:
    """True if sprint dict has in-progress stories."""
    return has_stories_with_status_data(data, "in-progress")


def has_reviewing_stories(smm_dir: Path) -> bool:
    """True if sprint has reviewing stories."""
    return has_stories_with_status(smm_dir, "reviewing")


def has_reviewing_stories_data(data: dict) -> bool:
    """True if sprint dict has reviewing stories."""
    return has_stories_with_status_data(data, "reviewing")


def has_closing_stories(smm_dir: Path) -> bool:
    """True if sprint has closing stories."""
    return has_stories_with_status(smm_dir, "closing")


def has_closing_stories_data(data: dict) -> bool:
    """True if sprint dict has closing stories."""
    return has_stories_with_status_data(data, "closing")


def select_closing_stories(stories: list[dict]) -> list[dict]:
    """Return stories in the /xp-story-close pipeline."""
    return [s for s in stories if s.get("status") == "closing"]


def has_in_motion_stories(smm_dir: Path) -> bool:
    """True if sprint has in-motion (in-progress, reviewing, or closing) stories."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    return has_in_motion_stories_data(sprint)


def has_in_motion_stories_data(data: dict) -> bool:
    """True if sprint dict has in-motion stories (in-progress, reviewing, closing)."""
    return any(s["status"] in IN_MOTION_STORY_STATUSES for s in data["stories"])


def select_in_motion_stories(stories: list[dict]) -> list[dict]:
    """Return stories under acceptance (in-progress, reviewing, or closing)."""
    return [s for s in stories if s.get("status") in IN_MOTION_STORY_STATUSES]


def has_ready_stories(smm_dir: Path) -> bool:
    """True if sprint has ready stories."""
    return has_stories_with_status(smm_dir, "ready")


def has_scheduled_stories(smm_dir: Path) -> bool:
    """True if sprint has scheduled stories (queued for this iteration)."""
    return has_stories_with_status(smm_dir, "scheduled")


def scheduled_file_domains_overlap(smm_dir: Path) -> bool:
    """True when 2+ scheduled stories share at least one file in their
    file_domain.

    Powers /xp-assign's auto-pick-solo decision: if any scheduled stories'
    file_domains overlap, parallel teammates would step on each other —
    auto-pick solo without asking the user. Returns False when fewer than
    two scheduled stories exist (no pair to overlap).

    Reuses the canonical em-dash splitter from `triage` so parsing matches
    every other consumer of file_domain entries (paths with embedded
    whitespace work correctly; descriptions don't mask shared files).
    """
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return False
    scheduled = [s for s in sprint["stories"] if s.get("status") == "scheduled"]
    if len(scheduled) < 2:
        return False

    # No cwd= — sprint stories declare literal paths; glob entries raise.
    path_sets = [
        extract_file_domain_paths(s.get("file_domain") or []) for s in scheduled
    ]
    return any(a & b for a, b in combinations(path_sets, 2))


def is_complete(smm_dir: Path) -> bool:
    """True when no ready or in-progress stories remain."""
    from sprint_store import load_sprint

    sprint = load_sprint(smm_dir)
    if sprint is None:
        return True
    if not sprint["stories"]:
        return True
    return not has_active_stories_data(sprint)
