#!/usr/bin/env python3
"""Schema constants and validator for sprint.json.

Single source of truth for what constitutes a valid sprint document.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as execution_plan_schema.py.
"""

from _acceptance_execution import (
    validate_acceptance_execution,
    validate_per_ac_verify,
)
from execution_plan_schema import VALID_BRANCH_NAME_RE
from schema_helpers import budget_error

SPRINT_FILENAME = "sprint.json"

VALID_STORY_STATUSES = frozenset(
    {"ready", "scheduled", "in-progress", "reviewing", "closing", "done", "deferred"}
)
TERMINAL_STORY_STATUSES = frozenset({"done", "deferred"})
ACTIVE_STORY_STATUSES = VALID_STORY_STATUSES - TERMINAL_STORY_STATUSES
# Stories with work currently in motion: branched + actively edited or
# under acceptance verification. Narrower than ACTIVE (which also covers
# ready/scheduled — pre-branch states). Drives cascade-deferral: a
# deferred story's in-motion descendants are invalidated. `closing`
# is the sprint-singleton state held while a story is inside the
# /xp-story-close pipeline. Orphan-branch detection uses
# ACTIVE_STORY_STATUSES, not this set.
IN_MOTION_STORY_STATUSES = frozenset({"in-progress", "reviewing", "closing"})
# Stories inside the per-story accept dispatch window
# (xp-accept → xp-story-close → mark-done). Subset of IN_MOTION minus
# in-progress. Used by the .accept marker re-arm guard
# (pre_tool_write.py) and the stop-gate accept message
# (sprint_stop_gate.py): both want a single predicate covering the
# close-then-done window without enumerating reviewing/closing
# separately at every call site.
UNDER_ACCEPTANCE_STORY_STATUSES = frozenset({"reviewing", "closing"})

# How a story is executed once its frontier is promoted. Set by
# /xp-schedule; read by the plan-review gate (subagent_stop) to decide
# whether to arm .assign-pending (teammate only). Optional story field —
# absent means not-yet-promoted.
VALID_EXECUTION_MODES = frozenset({"solo", "teammate"})

# Which model the lead picks for a teammate's spawn during per-story
# planning. Forwarded by /xp-assign to spawn_teammate.py --model.
# Optional story field — absent means inherit the lead's model.
# Closed plugin-side enum; widen here if a new tier ships
# (tests/agents/test_agent_model_tiers.py is the per-tier classification).
VALID_EXECUTOR_MODELS = frozenset({"sonnet", "opus", "haiku"})

STORY_FIELD_MAXLENGTH: dict[str, int] = {
    "context": 600,
}

STORY_ITEM_MAXLENGTH: dict[str, int] = {
    "file_domain": 200,
}

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
        "branch_name": None,
        "stories": [],
    }


def _validate_story(
    story: object,
    idx: int,
    *,
    enforce_budget: bool = True,
    valid_surfaces: frozenset[str] | None = None,
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

    if isinstance(story["acceptance_criteria"], list):
        for ac_idx, item in enumerate(story["acceptance_criteria"]):
            errors.extend(
                validate_per_ac_verify(
                    item,
                    f"stories[{idx}].acceptance_criteria[{ac_idx}]",
                    valid_surfaces=valid_surfaces,
                )
            )

    if enforce_budget and isinstance(story.get("context"), str):
        max_len = STORY_FIELD_MAXLENGTH["context"]
        actual = len(story["context"])
        if actual > max_len:
            errors.append(budget_error(f"stories[{idx}].context", actual, max_len))

    if enforce_budget and isinstance(story.get("file_domain"), list):
        fd_max = STORY_ITEM_MAXLENGTH["file_domain"]
        for fd_idx, item in enumerate(story["file_domain"]):
            if isinstance(item, str):
                actual = len(item)
                if actual > fd_max:
                    errors.append(
                        budget_error(
                            f"stories[{idx}].file_domain[{fd_idx}]", actual, fd_max
                        )
                    )

    ae = story.get("acceptance_execution")
    if ae is not None:
        errors.extend(
            validate_acceptance_execution(ae, f"stories[{idx}].acceptance_execution")
        )

    bn = story.get("branch_name")
    if bn is not None:
        if not isinstance(bn, str):
            errors.append(f"stories[{idx}].branch_name must be a string or null")
        elif not VALID_BRANCH_NAME_RE.match(bn):
            errors.append(
                f"stories[{idx}].branch_name is not a valid git branch name: {bn!r}"
            )

    em = story.get("execution_mode")
    if em is not None:
        if not isinstance(em, str):
            errors.append(f"stories[{idx}].execution_mode must be a string or null")
        elif em not in VALID_EXECUTION_MODES:
            valid = sorted(VALID_EXECUTION_MODES)
            errors.append(
                f"stories[{idx}].execution_mode must be one of {valid}, got {em!r}"
            )

    em_executor = story.get("executor_model")
    if em_executor is not None:
        if not isinstance(em_executor, str):
            errors.append(f"stories[{idx}].executor_model must be a string or null")
        elif em_executor not in VALID_EXECUTOR_MODELS:
            valid = sorted(VALID_EXECUTOR_MODELS)
            errors.append(
                f"stories[{idx}].executor_model must be one of {valid}, "
                f"got {em_executor!r}"
            )

    return errors


def validate_sprint(
    data: object,
    *,
    enforce_budget: bool = True,
    valid_surfaces: frozenset[str] | None = None,
) -> list[str]:
    """Validate a sprint document.

    Returns a list of error strings — empty list means valid.
    When enforce_budget is False, field-length budgets are skipped
    (read-path grandfathering, matching execution_plan_schema precedent).
    When valid_surfaces is supplied, each story's per-AC ``surface`` must be
    one of those names (FK to acceptance_surfaces); None keeps it shape-only.
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

    bn = data.get("branch_name")
    if bn is not None:
        if not isinstance(bn, str):
            errors.append("branch_name must be a string or null")
        elif not VALID_BRANCH_NAME_RE.match(bn):
            errors.append(f"branch_name is not a valid git branch name: {bn!r}")

    if not isinstance(data["stories"], list):
        errors.append("stories must be a list")
    else:
        for idx, story in enumerate(data["stories"]):
            errors.extend(
                _validate_story(
                    story,
                    idx,
                    enforce_budget=enforce_budget,
                    valid_surfaces=valid_surfaces,
                )
            )

    return errors
