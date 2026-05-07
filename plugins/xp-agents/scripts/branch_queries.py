#!/usr/bin/env python3
"""Branch listing and orphan detection queries.

Provides functions to list story branches and detect orphans (story
branches not backed by an active sprint story). Used by the kickoff
preload and CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import sprint_store
from sprint_schema import ACTIVE_STORY_STATUSES


def list_story_branches(cwd: str) -> list[str]:
    """Return story branches owned by the current user, excluding HEAD."""
    return branching.list_user_branches(cwd, "story")


def list_orphan_story_branches(cwd: str, smm_dir: Path) -> list[str]:
    """Return story branches not referenced by an active story in the sprint.

    A branch is orphan when no sprint exists, or its name doesn't match
    any non-terminal story's branch_name (see
    ``sprint_schema.ACTIVE_STORY_STATUSES``). Reviewing stories are
    mid-acceptance and closing stories are mid-merge — their branches
    stay alive for /xp-accept's verification cycle and /xp-story-close's
    merge step and must NOT be flagged orphan.
    """
    all_story = list_story_branches(cwd)
    if not all_story:
        return []
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return all_story
    active_branches = {
        s["branch_name"]
        for s in sprint["stories"]
        if s.get("status") in ACTIVE_STORY_STATUSES and s.get("branch_name")
    }
    return [b for b in all_story if b not in active_branches]
