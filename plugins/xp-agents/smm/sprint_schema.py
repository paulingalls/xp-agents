#!/usr/bin/env python3
"""Schema constants and validator for sprint.json.

Single source of truth for what constitutes a valid sprint document.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as execution_plan_schema.py.
"""

SPRINT_FILENAME = "sprint.json"

VALID_STORY_STATUSES = frozenset({"ready", "in-progress", "done", "deferred"})

STORY_FIELD_MAXLENGTH: dict[str, int] = {
    "context": 600,
}

STORY_ITEM_MAXLENGTH: dict[str, int] = {
    "file_domain": 200,
}

_ACTIVE_STATUSES = frozenset({"ready", "in-progress"})

_SPRINT_REQUIRED = frozenset({"sprint_id", "goal", "started", "stories"})

_STORY_REQUIRED = frozenset(
    {
        "id",
        "title",
        "status",
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


def _validate_story(
    story: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
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

    for field in (
        "dependencies",
        "file_domain",
        "interface_contracts",
        "acceptance_criteria",
    ):
        if not isinstance(story[field], list):
            errors.append(f"stories[{idx}].{field} must be a list")

    if enforce_budget and isinstance(story.get("context"), str):
        max_len = STORY_FIELD_MAXLENGTH["context"]
        actual = len(story["context"])
        if actual > max_len:
            errors.append(
                f"stories[{idx}].context exceeds budget ({actual} > {max_len} chars)"
            )

    if enforce_budget and isinstance(story.get("file_domain"), list):
        fd_max = STORY_ITEM_MAXLENGTH["file_domain"]
        for fd_idx, item in enumerate(story["file_domain"]):
            if isinstance(item, str):
                actual = len(item)
                if actual > fd_max:
                    errors.append(
                        f"stories[{idx}].file_domain[{fd_idx}]"
                        f" exceeds budget ({actual} > {fd_max} chars)"
                    )

    ae = story.get("acceptance_execution")
    if ae is not None:
        if not isinstance(ae, dict):
            errors.append(f"stories[{idx}].acceptance_execution must be an object")
        else:
            if not isinstance(ae.get("type"), str):
                errors.append(
                    f"stories[{idx}].acceptance_execution.type is required"
                    " and must be a string"
                )
            if not isinstance(ae.get("command"), str):
                errors.append(
                    f"stories[{idx}].acceptance_execution.command is required"
                    " and must be a string"
                )

    return errors


def validate_sprint(data: object, *, enforce_budget: bool = True) -> list[str]:
    """Validate a sprint document.

    Returns a list of error strings — empty list means valid.
    When enforce_budget is False, field-length budgets are skipped
    (read-path grandfathering, matching execution_plan_schema precedent).
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
            errors.extend(_validate_story(story, idx, enforce_budget=enforce_budget))

    return errors
