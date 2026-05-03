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


def list_story_branches(cwd: str) -> list[str]:
    """Return story branches owned by the current user, excluding HEAD."""
    return branching.list_user_branches(cwd, "story")


def list_orphan_story_branches(cwd: str, smm_dir: Path) -> list[str]:
    """Return story branches not referenced by an active story in the sprint.

    A branch is orphan when no sprint exists, or its name doesn't match
    any ready/in-progress/reviewing story's branch_name field. Reviewing
    stories are mid-acceptance — their branches are intentionally alive
    for /xp-accept's verification cycle and must NOT be flagged orphan.
    """
    all_story = list_story_branches(cwd)
    if not all_story:
        return []
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return all_story
    active = (
        sprint_store.list_stories(sprint, status="ready")
        + sprint_store.list_stories(sprint, status="in-progress")
        + sprint_store.list_stories(sprint, status="reviewing")
    )
    active_branches = {s.get("branch_name") for s in active if s.get("branch_name")}
    return [b for b in all_story if b not in active_branches]
