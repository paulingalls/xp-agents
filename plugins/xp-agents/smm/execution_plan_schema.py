#!/usr/bin/env python3
"""Schema constants and validator for execution_plan.json.

Single source of truth for what constitutes a valid execution plan.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as smm_schema.py: hand-rolled validator,
no external jsonschema dependency, stdlib-only.
"""

PLAN_FILENAME = "execution_plan.json"

VALID_MILESTONE_STATUSES = frozenset({"planned", "in-progress", "delivered"})
VALID_SOURCE_TYPES = frozenset({"repo", "url", "pasted"})

_MILESTONE_REQUIRED = frozenset(
    {
        "number",
        "name",
        "status",
        "delivered_sprint",
        "goal",
        "done",
        "sources",
        "change_zones",
        "impact_zones",
        "design_details",
        "constraints",
    }
)

_SOURCE_REQUIRED = frozenset({"label", "location", "type"})


def empty_plan() -> dict:
    """Return a canonical empty plan document."""
    return {
        "title": "",
        "sources": [],
        "overview": "",
        "milestones": [],
    }


def _validate_zone_entry(
    entry: object, field_name: str, idx: int, m_idx: int
) -> list[str]:
    """Validate a change_zone or impact_zone entry."""
    errors: list[str] = []
    prefix = f"milestones[{m_idx}].{field_name}[{idx}]"
    if not isinstance(entry, dict):
        errors.append(f"{prefix} must be an object")
        return errors
    if "path" not in entry:
        errors.append(f"{prefix} missing required field: path")
    elif not isinstance(entry["path"], str):
        errors.append(f"{prefix}.path must be a string")
    return errors


def _validate_source(source: object, idx: int) -> list[str]:
    """Validate a source entry."""
    errors: list[str] = []
    if not isinstance(source, dict):
        return [f"sources[{idx}] must be an object"]

    for field in _SOURCE_REQUIRED:
        if field not in source:
            errors.append(f"sources[{idx}] missing required field: {field}")

    if errors:
        return errors

    if not isinstance(source["label"], str):
        errors.append(f"sources[{idx}].label must be a string")
    if not isinstance(source["location"], str):
        errors.append(f"sources[{idx}].location must be a string")
    if source["type"] not in VALID_SOURCE_TYPES:
        errors.append(
            f"sources[{idx}].type must be one of {sorted(VALID_SOURCE_TYPES)}"
        )
    return errors


def _validate_milestone(milestone: object, idx: int) -> list[str]:
    """Validate a milestone entry."""
    errors: list[str] = []
    if not isinstance(milestone, dict):
        return [f"milestones[{idx}] must be an object"]

    for field in _MILESTONE_REQUIRED:
        if field not in milestone:
            errors.append(f"milestones[{idx}] missing required field: {field}")

    if errors:
        return errors

    if not isinstance(milestone["number"], int):
        errors.append(f"milestones[{idx}].number must be an integer")

    if not isinstance(milestone["name"], str):
        errors.append(f"milestones[{idx}].name must be a string")

    valid_statuses = sorted(VALID_MILESTONE_STATUSES)
    if milestone["status"] not in VALID_MILESTONE_STATUSES:
        errors.append(f"milestones[{idx}].status must be one of {valid_statuses}")

    # Sprint ID tracks when/how a milestone shipped — needed for history
    if milestone["status"] == "delivered" and not milestone.get("delivered_sprint"):
        errors.append(
            f"milestones[{idx}].delivered_sprint is required when status is 'delivered'"
        )

    if not isinstance(milestone["goal"], str):
        errors.append(f"milestones[{idx}].goal must be a string")

    if not isinstance(milestone["done"], str):
        errors.append(f"milestones[{idx}].done must be a string")

    # change_zones and impact_zones must be lists of objects with path
    for field in ("change_zones", "impact_zones"):
        value = milestone[field]
        if not isinstance(value, list):
            errors.append(f"milestones[{idx}].{field} must be a list")
        else:
            for z_idx, zone in enumerate(value):
                errors.extend(_validate_zone_entry(zone, field, z_idx, idx))

    if not isinstance(milestone["constraints"], list):
        errors.append(f"milestones[{idx}].constraints must be a list")

    return errors


def validate_plan(data: object) -> list[str]:
    """Validate an execution plan document.

    Returns a list of error strings — empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Execution plan must be an object"]

    for field in ("title", "sources", "overview", "milestones"):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    if not isinstance(data["title"], str):
        errors.append("title must be a string")

    if not isinstance(data["overview"], str):
        errors.append("overview must be a string")

    if not isinstance(data["sources"], list):
        errors.append("sources must be a list")
    else:
        for idx, source in enumerate(data["sources"]):
            errors.extend(_validate_source(source, idx))

    if not isinstance(data["milestones"], list):
        errors.append("milestones must be a list")
    else:
        for idx, milestone in enumerate(data["milestones"]):
            errors.extend(_validate_milestone(milestone, idx))

    return errors
