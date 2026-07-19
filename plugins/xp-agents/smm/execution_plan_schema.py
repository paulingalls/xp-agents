#!/usr/bin/env python3
"""Schema constants and validator for execution_plan.json.

Single source of truth for what constitutes a valid execution plan.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as smm_schema.py: hand-rolled validator,
no external jsonschema dependency, stdlib-only.
"""

import re

from _acceptance_execution import validate_acceptance_execution
from schema_helpers import budget_error
from smm_schema import EVENT_ID_RE

PLAN_FILENAME = "execution_plan.json"

VALID_MILESTONE_STATUSES = frozenset(
    {"planned", "in-progress", "delivered", "deferred"}
)
VALID_SOURCE_TYPES = frozenset({"repo", "url", "pasted"})

# `\Z`, not `$`: Python's `$` also matches BEFORE a trailing newline, so `$`
# here accepted "main\n" as a valid branch name. These values become `git
# checkout <ref>` / `git merge <ref>` arguments and get interpolated into the
# preload's KEY=value contract, where a newline forges a line at column 0. A
# trailing newline is never part of a legitimate branch name, so this only
# rejects input that was already broken.
VALID_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\Z")

MILESTONE_FIELD_MAXLENGTH: dict[str, int] = {
    "goal": 200,
    "done": 300,
    "design_details": 800,
}

MILESTONE_ITEM_MAXLENGTH: dict[str, int] = {
    "constraints": 150,
    "zone_note": 150,
}

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
    entry: object,
    field_name: str,
    idx: int,
    m_idx: int,
    *,
    enforce_budget: bool = True,
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

    if "note" in entry:
        if not isinstance(entry["note"], str):
            errors.append(f"{prefix}.note must be a string")
        elif enforce_budget:
            max_len = MILESTONE_ITEM_MAXLENGTH["zone_note"]
            actual = len(entry["note"])
            if actual > max_len:
                errors.append(budget_error(f"{prefix}.note", actual, max_len))

    return errors


def _validate_schedules(milestone: dict, m_idx: int) -> list[str]:
    """Validate a milestone's optional ``schedules``: the recorded event ids
    (debts, concerns) this milestone is being written to resolve.

    STRUCTURAL, replacing prose inference. Consumers (the retrospective) read it
    to answer "is this aging debt already scheduled?" — a question they used to
    answer by substring-matching ids inside LLM-authored zone notes. A note
    naming an id is not evidence it schedules it: the note may be citing the
    item, or rejecting it. Only an author can say, and this is where they say it.

    The authoring rule is one question — "when this milestone ships, is the item
    resolved?" — and it turns on the item's DEFECT, not on the remedy the item
    proposed. A milestone that fixes the defect a different way than the debt
    prescribed still resolves it, and still belongs here.

    Lives on the MILESTONE, not on a zone entry: `_validate_zone_entry` is shared
    by `change_zones` and `impact_zones`, and an impact-zone ref would mean
    "touched", not "scheduled".

    Named `schedules`, NOT `refs` — `refs` already names the `[refs: id]` content
    suffix that routes to metadata.resolves/references. Ids are validated against
    smm_schema.EVENT_ID_RE, the one id pattern; this module hand-rolls no second.

    Optional: absent means "this milestone names nothing", which is what every
    plan authored before this field says.
    """
    if "schedules" not in milestone:
        return []

    errors: list[str] = []
    prefix = f"milestones[{m_idx}].schedules"
    value = milestone["schedules"]
    if not isinstance(value, list):
        return [f"{prefix} must be a list of event ids"]

    for s_idx, event_id in enumerate(value):
        if not isinstance(event_id, str) or not EVENT_ID_RE.match(event_id):
            errors.append(f"{prefix}[{s_idx}] must be a 12-hex event id")
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


def _validate_milestone(
    milestone: object,
    idx: int,
    *,
    enforce_budget: bool = True,
    valid_surfaces: frozenset[str] | None = None,
) -> list[str]:
    """Validate a milestone entry.

    ``surfaces_touched`` is an optional ``list[str]``. When
    ``valid_surfaces`` is supplied, each entry must be one of those names
    (FK to ``acceptance_surfaces[*].name``); when ``None``, only the
    list-of-strings shape is checked.
    """
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

    _str_fields = ("goal", "done", "design_details")
    for field in _str_fields:
        val = milestone[field]
        if not isinstance(val, str):
            errors.append(f"milestones[{idx}].{field} must be a string")
        elif enforce_budget:
            max_len = MILESTONE_FIELD_MAXLENGTH[field]
            actual = len(val)
            if actual > max_len:
                errors.append(
                    budget_error(f"milestones[{idx}].{field}", actual, max_len)
                )

    # change_zones and impact_zones must be lists of objects with path
    for field in ("change_zones", "impact_zones"):
        value = milestone[field]
        if not isinstance(value, list):
            errors.append(f"milestones[{idx}].{field} must be a list")
        else:
            for z_idx, zone in enumerate(value):
                errors.extend(
                    _validate_zone_entry(
                        zone, field, z_idx, idx, enforce_budget=enforce_budget
                    )
                )

    if not isinstance(milestone["constraints"], list):
        errors.append(f"milestones[{idx}].constraints must be a list")
    else:
        c_max = MILESTONE_ITEM_MAXLENGTH["constraints"]
        for c_idx, item in enumerate(milestone["constraints"]):
            if not isinstance(item, str):
                errors.append(
                    f"milestones[{idx}].constraints[{c_idx}] must be a string"
                )
            elif enforce_budget:
                actual = len(item)
                if actual > c_max:
                    errors.append(
                        budget_error(
                            f"milestones[{idx}].constraints[{c_idx}]", actual, c_max
                        )
                    )

    ae = milestone.get("acceptance_execution")
    if ae is not None:
        errors.extend(
            validate_acceptance_execution(
                ae,
                f"milestones[{idx}].acceptance_execution",
                allow_pins=False,
            )
        )

    errors.extend(_validate_schedules(milestone, idx))

    if "surfaces_touched" in milestone:
        st = milestone["surfaces_touched"]
        prefix = f"milestones[{idx}].surfaces_touched"
        if not isinstance(st, list):
            errors.append(f"{prefix} must be a list of strings")
        else:
            for s_idx, name in enumerate(st):
                if not isinstance(name, str):
                    errors.append(f"{prefix}[{s_idx}] must be a string")
                elif valid_surfaces is not None and name not in valid_surfaces:
                    errors.append(
                        f"{prefix}[{s_idx}] references unknown surface {name!r}"
                    )

    return errors


def validate_plan(
    data: object,
    *,
    enforce_budget: bool = True,
    valid_surfaces: frozenset[str] | None = None,
) -> list[str]:
    """Validate an execution plan document.

    Returns a list of error strings — empty list means valid.
    When enforce_budget is False, field-length budgets are skipped
    (read-path grandfathering, matching smm_schema precedent).
    When valid_surfaces is supplied, milestone.surfaces_touched entries
    are FK-checked against it; when None, only their shape is validated.
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

    branch = data.get("branch")
    if branch is not None:
        if not isinstance(branch, str):
            errors.append("branch must be a string")
        elif not VALID_BRANCH_NAME_RE.match(branch):
            errors.append(f"branch is not a valid git branch name: {branch!r}")

    if not isinstance(data["sources"], list):
        errors.append("sources must be a list")
    else:
        for idx, source in enumerate(data["sources"]):
            errors.extend(_validate_source(source, idx))

    if not isinstance(data["milestones"], list):
        errors.append("milestones must be a list")
    else:
        for idx, milestone in enumerate(data["milestones"]):
            errors.extend(
                _validate_milestone(
                    milestone,
                    idx,
                    enforce_budget=enforce_budget,
                    valid_surfaces=valid_surfaces,
                )
            )

    return errors
