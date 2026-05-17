#!/usr/bin/env python3
"""Entry validators + constants for acceptance_surfaces and project_specific lists."""

import json

from schema_helpers import budget_error

PROJECT_SPECIFIC_NAME_MAXLENGTH: int = 50
PROJECT_SPECIFIC_CONTENT_MAXLENGTH: int = 500

ACCEPTANCE_SURFACE_NAME_MAXLENGTH: int = 50
ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH: int = 50
ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH: int = 100

_ACCEPTANCE_SURFACE_REQUIRED = frozenset({"name", "signals", "status"})
_VALID_SURFACE_STATUSES = frozenset({"covered", "gap"})


def _validate_acceptance_surface_entry(
    entry: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"acceptance_surfaces[{idx}] must be an object"]

    for field in _ACCEPTANCE_SURFACE_REQUIRED:
        if field not in entry:
            errors.append(f"acceptance_surfaces[{idx}] missing required field: {field}")

    if errors:
        return errors

    if not isinstance(entry["name"], str):
        errors.append(f"acceptance_surfaces[{idx}].name must be a string")
    elif enforce_budget and len(entry["name"]) > ACCEPTANCE_SURFACE_NAME_MAXLENGTH:
        errors.append(
            budget_error(
                f"acceptance_surfaces[{idx}].name",
                len(entry["name"]),
                ACCEPTANCE_SURFACE_NAME_MAXLENGTH,
            )
        )

    if not isinstance(entry["signals"], list):
        errors.append(f"acceptance_surfaces[{idx}].signals must be a list")
    else:
        for si, sig in enumerate(entry["signals"]):
            if not isinstance(sig, str):
                errors.append(
                    f"acceptance_surfaces[{idx}].signals[{si}] must be a string"
                )
            elif enforce_budget and len(sig) > ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH:
                errors.append(
                    budget_error(
                        f"acceptance_surfaces[{idx}].signals[{si}]",
                        len(sig),
                        ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH,
                    )
                )

    status = entry["status"]
    if not isinstance(status, str):
        errors.append(f"acceptance_surfaces[{idx}].status must be a string")
    elif status not in _VALID_SURFACE_STATUSES:
        errors.append(
            f"acceptance_surfaces[{idx}].status must be one of"
            f" {sorted(_VALID_SURFACE_STATUSES)} (got {status!r})"
        )

    if "harness" in entry:
        if not isinstance(entry["harness"], str):
            errors.append(f"acceptance_surfaces[{idx}].harness must be a string")
        elif (
            enforce_budget
            and len(entry["harness"]) > ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH
        ):
            errors.append(
                budget_error(
                    f"acceptance_surfaces[{idx}].harness",
                    len(entry["harness"]),
                    ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH,
                )
            )

    return errors


def _validate_project_specific_entry(
    entry: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"project_specific[{idx}] must be an object"]

    if "name" not in entry:
        errors.append(f"project_specific[{idx}] missing required field: name")
    elif not isinstance(entry["name"], str):
        errors.append(f"project_specific[{idx}].name must be a string")
    elif enforce_budget and len(entry["name"]) > PROJECT_SPECIFIC_NAME_MAXLENGTH:
        errors.append(
            budget_error(
                f"project_specific[{idx}].name",
                len(entry["name"]),
                PROJECT_SPECIFIC_NAME_MAXLENGTH,
            )
        )

    if "content" not in entry:
        errors.append(f"project_specific[{idx}] missing required field: content")
    elif enforce_budget:
        serialized = json.dumps(entry["content"])
        if len(serialized) > PROJECT_SPECIFIC_CONTENT_MAXLENGTH:
            errors.append(
                budget_error(
                    f"project_specific[{idx}].content",
                    len(serialized),
                    PROJECT_SPECIFIC_CONTENT_MAXLENGTH,
                )
            )

    return errors
