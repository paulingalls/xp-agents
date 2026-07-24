#!/usr/bin/env python3
"""Schema constants and validator for system_context.json.

Single source of truth for what constitutes a valid system context document.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as execution_plan_schema.py: hand-rolled validator,
no external jsonschema dependency, stdlib-only.
"""

from schema_helpers import budget_error
from smm_schema import EVENT_ID_RE

# Re-export shim per the split convention — extracted constants/validators
# keep the historical import path working for callers (e.g. tests).
from system_context_branching_validators import (  # noqa: F401
    _BRANCHING_STRATEGY_REQUIRED,
    BRANCHING_STRATEGY_FIELD_MAXLENGTH,
    _usable_ref_segment,
    _validate_branching_strategy,
    healed_integration_branch,
    healed_user_namespace,
    integration_branch_error,
    user_namespace_error,
)
from system_context_entry_validators import (  # noqa: F401
    ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH,
    ACCEPTANCE_SURFACE_NAME_MAXLENGTH,
    ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH,
    PROJECT_SPECIFIC_CONTENT_MAXLENGTH,
    PROJECT_SPECIFIC_NAME_MAXLENGTH,
    _validate_acceptance_surface_entry,
    _validate_project_specific_entry,
    _validate_test_layout,
)

SYSTEM_CONTEXT_FILENAME = "system_context.json"

FIELD_MAXLENGTH: dict[str, int] = {
    "product": 400,
    # 750 chars: headroom for multi-component systems with several
    # persistent files + cross-cutting orchestration. 600 was tight on
    # repos with 5+ persistent state files (e.g., this plugin: SMM
    # four-file architecture + session_history.json). xp-system-
    # analyzer.md's Step 4 JSON template documents the same number —
    # kept in sync by
    # test_agent_prompts.TestSystemAnalyzerPromptMaxlengthSync.
    "architecture_overview": 750,
}

STACK_FIELD_MAXLENGTH: int = 100
STACK_LANGUAGE_ITEM_MAXLENGTH: int = 30

MODULE_FIELD_MAXLENGTH: dict[str, int] = {
    "purpose": 100,
}
MODULE_NAME_MAXLENGTH: int = 50
MODULE_PATH_MAXLENGTH: int = 200

CONVENTION_MAXLENGTH: int = 150

MODULES_SOFT_CAP: int = 10
MODULES_HARD_CAP: int = 15
CONVENTIONS_SOFT_CAP: int = 20
CONVENTIONS_HARD_CAP: int = 30
PRINCIPLES_SOFT_CAP: int = 15
PRINCIPLES_HARD_CAP: int = 20
PROJECT_SPECIFIC_SOFT_CAP: int = 10
PROJECT_SPECIFIC_HARD_CAP: int = 15
ACCEPTANCE_SURFACES_SOFT_CAP: int = 5
ACCEPTANCE_SURFACES_HARD_CAP: int = 8

PRINCIPLE_FIELD_MAXLENGTH: dict[str, int] = {
    "decision": 200,
    "rationale": 200,
}
PRINCIPLE_TOPIC_MAXLENGTH: int = 60

_REQUIRED_FIELDS = frozenset(
    {
        "product",
        "architecture_overview",
        "stack",
        "modules",
        "conventions",
        "principles",
        "project_specific",
    }
)

# `test_command` is the full automated-test command (e.g.,
# "pytest -n auto", "npm test"). Read by close-skill preloads to gate
# the story-close + free-close auto-merge override; empty / unset →
# no auto-merge.
#
# `worktree_bootstrap` is a project-declared command run in a freshly
# created teammate worktree before the agent's first turn (see
# spawn_teammate.create_worktree). `git worktree add` materializes only
# tracked files, so gitignored state is absent — and absent state can go
# FALSELY GREEN rather than failing loud. The command is opaque to the
# plugin: only the project knows which gitignored state is
# checkout-invariant (installable) versus checkout-variant (must be
# regenerated, never copied), so the project's own script encodes that
# split.
STACK_OPTIONAL_FIELDS = (
    "runtime",
    "dependencies_policy",
    "package_manager",
    "test_command",
    "worktree_bootstrap",
)

_MODULE_REQUIRED = frozenset({"name", "purpose", "path"})

_PRINCIPLE_REQUIRED = frozenset({"topic", "decision"})


def empty_system_context() -> dict:
    """Return a canonical empty system context document."""
    return {
        "product": "",
        "architecture_overview": "",
        "stack": {"languages": []},
        "modules": [],
        "conventions": [],
        "principles": [],
        "project_specific": [],
    }


def _validate_stack(stack: object, *, enforce_budget: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(stack, dict):
        return ["stack must be an object"]

    if "languages" not in stack:
        errors.append("stack missing required field: languages")
    elif not isinstance(stack["languages"], list):
        errors.append("stack.languages must be a list")
    else:
        for idx, lang in enumerate(stack["languages"]):
            if not isinstance(lang, str):
                errors.append(f"stack.languages[{idx}] must be a string")
            elif enforce_budget and len(lang) > STACK_LANGUAGE_ITEM_MAXLENGTH:
                errors.append(
                    budget_error(
                        f"stack.languages[{idx}]",
                        len(lang),
                        STACK_LANGUAGE_ITEM_MAXLENGTH,
                    )
                )

    for field in STACK_OPTIONAL_FIELDS:
        if field not in stack:
            continue
        if not isinstance(stack[field], str):
            errors.append(f"stack.{field} must be a string")
        elif enforce_budget and len(stack[field]) > STACK_FIELD_MAXLENGTH:
            errors.append(
                budget_error(f"stack.{field}", len(stack[field]), STACK_FIELD_MAXLENGTH)
            )

    return errors


def _validate_module(
    module: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(module, dict):
        return [f"modules[{idx}] must be an object"]

    for field in _MODULE_REQUIRED:
        if field not in module:
            errors.append(f"modules[{idx}] missing required field: {field}")

    if errors:
        return errors

    for field in _MODULE_REQUIRED:
        if not isinstance(module[field], str):
            errors.append(f"modules[{idx}].{field} must be a string")

    if enforce_budget and isinstance(module.get("purpose"), str):
        max_len = MODULE_FIELD_MAXLENGTH["purpose"]
        actual = len(module["purpose"])
        if actual > max_len:
            errors.append(budget_error(f"modules[{idx}].purpose", actual, max_len))

    if enforce_budget and isinstance(module.get("name"), str):
        actual = len(module["name"])
        if actual > MODULE_NAME_MAXLENGTH:
            errors.append(
                budget_error(f"modules[{idx}].name", actual, MODULE_NAME_MAXLENGTH)
            )

    if enforce_budget and isinstance(module.get("path"), str):
        actual = len(module["path"])
        if actual > MODULE_PATH_MAXLENGTH:
            errors.append(
                budget_error(f"modules[{idx}].path", actual, MODULE_PATH_MAXLENGTH)
            )

    if "file_count" in module and not isinstance(module["file_count"], int):
        errors.append(f"modules[{idx}].file_count must be an integer")

    return errors


def _validate_principle(
    decision: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(decision, dict):
        return [f"principles[{idx}] must be an object"]

    for field in _PRINCIPLE_REQUIRED:
        if field not in decision:
            errors.append(f"principles[{idx}] missing required field: {field}")

    if errors:
        return errors

    for field in _PRINCIPLE_REQUIRED:
        if not isinstance(decision[field], str):
            errors.append(f"principles[{idx}].{field} must be a string")

    if enforce_budget:
        for field, max_len in PRINCIPLE_FIELD_MAXLENGTH.items():
            if field in decision and isinstance(decision[field], str):
                actual = len(decision[field])
                if actual > max_len:
                    errors.append(
                        budget_error(f"principles[{idx}].{field}", actual, max_len)
                    )

    if enforce_budget and isinstance(decision.get("topic"), str):
        actual = len(decision["topic"])
        if actual > PRINCIPLE_TOPIC_MAXLENGTH:
            errors.append(
                budget_error(
                    f"principles[{idx}].topic", actual, PRINCIPLE_TOPIC_MAXLENGTH
                )
            )

    if "rationale" in decision and not isinstance(decision["rationale"], str):
        errors.append(f"principles[{idx}].rationale must be a string")

    if "source_event_id" in decision:
        val = decision["source_event_id"]
        if not isinstance(val, str) or not EVENT_ID_RE.match(val):
            errors.append(f"principles[{idx}].source_event_id must be a 12-char hex ID")

    return errors


def validate_system_context(
    data: object, *, enforce_budget: bool = True, enforce_ref_format: bool = True
) -> list[str]:
    """Validate a system context document.

    Returns a list of error strings — empty list means valid.
    When enforce_budget is False, field-length budgets are skipped
    (read-path grandfathering, matching execution_plan_schema precedent).
    When enforce_ref_format is False, branching_strategy.integration_branch
    is type-checked but not held to the git-ref rule — the read path, so a
    stored value that predates the rule still LOADS. Leniency about format is
    not leniency about shape: a non-string is rejected either way.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["System context must be an object"]

    for field in _REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    for field, max_len in FIELD_MAXLENGTH.items():
        val = data[field]
        if not isinstance(val, str):
            errors.append(f"{field} must be a string")
        elif enforce_budget and len(val) > max_len:
            errors.append(budget_error(field, len(val), max_len))

    errors.extend(_validate_stack(data["stack"], enforce_budget=enforce_budget))

    if not isinstance(data["modules"], list):
        errors.append("modules must be a list")
    else:
        for idx, module in enumerate(data["modules"]):
            errors.extend(_validate_module(module, idx, enforce_budget=enforce_budget))

    if not isinstance(data["conventions"], list):
        errors.append("conventions must be a list")
    else:
        for idx, conv in enumerate(data["conventions"]):
            if not isinstance(conv, str):
                errors.append(f"conventions[{idx}] must be a string")
            elif enforce_budget and len(conv) > CONVENTION_MAXLENGTH:
                errors.append(
                    budget_error(f"conventions[{idx}]", len(conv), CONVENTION_MAXLENGTH)
                )

    if not isinstance(data["principles"], list):
        errors.append("principles must be a list")
    else:
        for idx, kd in enumerate(data["principles"]):
            errors.extend(_validate_principle(kd, idx, enforce_budget=enforce_budget))

    if not isinstance(data["project_specific"], list):
        errors.append("project_specific must be a list")
    else:
        seen_names: set[str] = set()
        for idx, entry in enumerate(data["project_specific"]):
            errors.extend(
                _validate_project_specific_entry(
                    entry, idx, enforce_budget=enforce_budget
                )
            )
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                if entry["name"] in seen_names:
                    errors.append(
                        f"project_specific[{idx}] duplicate name:"
                        f" {entry['name']!r} — names must be unique"
                    )
                else:
                    seen_names.add(entry["name"])

    if "branching_strategy" in data:
        errors.extend(
            _validate_branching_strategy(
                data["branching_strategy"],
                enforce_budget=enforce_budget,
                enforce_ref_format=enforce_ref_format,
            )
        )

    if "acceptance_surfaces" in data:
        surfaces = data["acceptance_surfaces"]
        if not isinstance(surfaces, list):
            errors.append("acceptance_surfaces must be a list")
        else:
            seen_surface_names: set[str] = set()
            for idx, entry in enumerate(surfaces):
                errors.extend(
                    _validate_acceptance_surface_entry(
                        entry, idx, enforce_budget=enforce_budget
                    )
                )
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    if entry["name"] in seen_surface_names:
                        errors.append(
                            f"acceptance_surfaces[{idx}] duplicate name:"
                            f" {entry['name']!r} — names must be unique"
                        )
                    else:
                        seen_surface_names.add(entry["name"])

    if "test_layout" in data:
        errors.extend(
            _validate_test_layout(data["test_layout"], enforce_budget=enforce_budget)
        )

    return errors
