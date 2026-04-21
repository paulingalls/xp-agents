#!/usr/bin/env python3
"""Schema constants and validator for system_context.json.

Single source of truth for what constitutes a valid system context document.
No I/O, no file operations — pure validation logic and shared constants.

Follows the same pattern as execution_plan_schema.py: hand-rolled validator,
no external jsonschema dependency, stdlib-only.
"""

from smm_schema import EVENT_ID_RE

SYSTEM_CONTEXT_FILENAME = "system_context.json"

FIELD_MAXLENGTH: dict[str, int] = {
    "product": 400,
    "architecture_overview": 600,
}

STACK_FIELD_MAXLENGTH: int = 100

MODULE_FIELD_MAXLENGTH: dict[str, int] = {
    "purpose": 200,
}

CONVENTION_MAXLENGTH: int = 150

KEY_DECISION_FIELD_MAXLENGTH: dict[str, int] = {
    "decision": 200,
    "rationale": 200,
}

_REQUIRED_FIELDS = frozenset(
    {
        "product",
        "architecture_overview",
        "stack",
        "modules",
        "conventions",
        "key_decisions",
        "sources",
        "project_specific",
    }
)

_STACK_OPTIONAL_FIELDS = ("runtime", "dependencies_policy", "package_manager")

_MODULE_REQUIRED = frozenset({"name", "purpose", "path"})

_KEY_DECISION_REQUIRED = frozenset({"topic", "decision"})


def empty_system_context() -> dict:
    """Return a canonical empty system context document."""
    return {
        "product": "",
        "architecture_overview": "",
        "stack": {"languages": []},
        "modules": [],
        "conventions": [],
        "key_decisions": [],
        "sources": [],
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

    for field in _STACK_OPTIONAL_FIELDS:
        if field not in stack:
            continue
        if not isinstance(stack[field], str):
            errors.append(f"stack.{field} must be a string")
        elif enforce_budget and len(stack[field]) > STACK_FIELD_MAXLENGTH:
            errors.append(
                f"stack.{field} exceeds budget"
                f" ({len(stack[field])} > {STACK_FIELD_MAXLENGTH} chars)"
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
            errors.append(
                f"modules[{idx}].purpose exceeds budget ({actual} > {max_len} chars)"
            )

    if "file_count" in module and not isinstance(module["file_count"], int):
        errors.append(f"modules[{idx}].file_count must be an integer")

    return errors


def _validate_key_decision(
    decision: object, idx: int, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(decision, dict):
        return [f"key_decisions[{idx}] must be an object"]

    for field in _KEY_DECISION_REQUIRED:
        if field not in decision:
            errors.append(f"key_decisions[{idx}] missing required field: {field}")

    if errors:
        return errors

    for field in _KEY_DECISION_REQUIRED:
        if not isinstance(decision[field], str):
            errors.append(f"key_decisions[{idx}].{field} must be a string")

    if enforce_budget:
        for field, max_len in KEY_DECISION_FIELD_MAXLENGTH.items():
            if field in decision and isinstance(decision[field], str):
                actual = len(decision[field])
                if actual > max_len:
                    errors.append(
                        f"key_decisions[{idx}].{field} exceeds budget"
                        f" ({actual} > {max_len} chars)"
                    )

    if "rationale" in decision and not isinstance(decision["rationale"], str):
        errors.append(f"key_decisions[{idx}].rationale must be a string")

    if "source_event_id" in decision:
        val = decision["source_event_id"]
        if not isinstance(val, str) or not EVENT_ID_RE.match(val):
            errors.append(
                f"key_decisions[{idx}].source_event_id must be a 12-char hex ID"
            )

    return errors


def _validate_project_specific_entry(entry: object, idx: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"project_specific[{idx}] must be an object"]

    if "name" not in entry:
        errors.append(f"project_specific[{idx}] missing required field: name")
    elif not isinstance(entry["name"], str):
        errors.append(f"project_specific[{idx}].name must be a string")

    if "content" not in entry:
        errors.append(f"project_specific[{idx}] missing required field: content")

    return errors


def validate_system_context(data: object, *, enforce_budget: bool = True) -> list[str]:
    """Validate a system context document.

    Returns a list of error strings — empty list means valid.
    When enforce_budget is False, field-length budgets are skipped
    (read-path grandfathering, matching execution_plan_schema precedent).
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
            errors.append(f"{field} exceeds budget ({len(val)} > {max_len} chars)")

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
                    f"conventions[{idx}] exceeds budget"
                    f" ({len(conv)} > {CONVENTION_MAXLENGTH} chars)"
                )

    if not isinstance(data["key_decisions"], list):
        errors.append("key_decisions must be a list")
    else:
        for idx, kd in enumerate(data["key_decisions"]):
            errors.extend(
                _validate_key_decision(kd, idx, enforce_budget=enforce_budget)
            )

    if not isinstance(data["sources"], list):
        errors.append("sources must be a list")
    else:
        for idx, src in enumerate(data["sources"]):
            if not isinstance(src, str):
                errors.append(f"sources[{idx}] must be a string")

    if not isinstance(data["project_specific"], list):
        errors.append("project_specific must be a list")
    else:
        seen_names: set[str] = set()
        for idx, entry in enumerate(data["project_specific"]):
            errors.extend(_validate_project_specific_entry(entry, idx))
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                if entry["name"] in seen_names:
                    errors.append(
                        f"project_specific[{idx}] duplicate name:"
                        f" {entry['name']!r} — names must be unique"
                    )
                else:
                    seen_names.add(entry["name"])

    return errors
