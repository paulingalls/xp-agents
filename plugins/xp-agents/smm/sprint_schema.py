#!/usr/bin/env python3
"""Schema constants and validator for sprint.json.

Single source of truth for what constitutes a valid sprint document.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as execution_plan_schema.py.
"""

SPRINT_FILENAME = "sprint.json"

VALID_STORY_STATUSES = frozenset({"ready", "in-progress", "done", "deferred"})
VALID_STORY_SIZES = frozenset({"S", "M", "L"})

_ACTIVE_STATUSES = frozenset({"ready", "in-progress"})

_SPRINT_REQUIRED = frozenset({"sprint_id", "goal", "started", "stories"})

_STORY_REQUIRED = frozenset(
    {
        "id",
        "title",
        "status",
        "size",
        "dependencies",
        "milestone_ref",
        "design_sources",
        "context",
        "file_domain",
        "interface_contracts",
        "acceptance_criteria",
    }
)


def empty_sprint() -> dict:
    """Return a canonical empty sprint document."""
    return {
        "sprint_id": "",
        "goal": "",
        "started": "",
        "milestone": "",
        "stories": [],
    }


def _validate_story(story: object, idx: int) -> list[str]:
    """Validate a story entry."""
    errors: list[str] = []
    if not isinstance(story, dict):
        return [f"stories[{idx}] must be an object"]

    for field in _STORY_REQUIRED:
        if field not in story:
            errors.append(f"stories[{idx}] missing required field: {field}")

    if errors:
        return errors

    if not isinstance(story["id"], str):
        errors.append(f"stories[{idx}].id must be a string")

    if not isinstance(story["title"], str):
        errors.append(f"stories[{idx}].title must be a string")

    if story["status"] not in VALID_STORY_STATUSES:
        valid = sorted(VALID_STORY_STATUSES)
        errors.append(f"stories[{idx}].status must be one of {valid}")

    if story["size"] not in VALID_STORY_SIZES:
        valid = sorted(VALID_STORY_SIZES)
        errors.append(f"stories[{idx}].size must be one of {valid}")

    for field in (
        "dependencies",
        "file_domain",
        "interface_contracts",
        "acceptance_criteria",
    ):
        if not isinstance(story[field], list):
            errors.append(f"stories[{idx}].{field} must be a list")

    return errors


def validate_sprint(data: object) -> list[str]:
    """Validate a sprint document.

    Returns a list of error strings — empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Sprint must be an object"]

    for field in _SPRINT_REQUIRED:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    if not isinstance(data["sprint_id"], str):
        errors.append("sprint_id must be a string")

    if not isinstance(data["goal"], str):
        errors.append("goal must be a string")

    if not isinstance(data["stories"], list):
        errors.append("stories must be a list")
    else:
        for idx, story in enumerate(data["stories"]):
            errors.extend(_validate_story(story, idx))

    return errors
