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

BRANCHING_STRATEGY_FIELD_MAXLENGTH: dict[str, int] = {
    "rationale": 300,
    "user_namespace": 50,
}

_BRANCHING_STRATEGY_REQUIRED = frozenset({"stage"})

_ACCEPTANCE_SURFACE_REQUIRED = frozenset({"name", "signals", "status"})
_VALID_SURFACE_STATUSES = frozenset({"covered", "gap"})

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


def _validate_branching_strategy(
    bs: object, *, enforce_budget: bool = True
) -> list[str]:
    errors: list[str] = []
    if not isinstance(bs, dict):
        return ["branching_strategy must be an object"]

    for field in _BRANCHING_STRATEGY_REQUIRED:
        if field not in bs:
            errors.append(f"branching_strategy missing required field: {field}")

    if errors:
        return errors

    stage = bs["stage"]
    if not isinstance(stage, int) or isinstance(stage, bool):
        errors.append("branching_strategy.stage must be an integer")
    elif stage < 0 or stage > 3:
        errors.append(f"branching_strategy.stage must be 0-3 (got {stage})")

    if "user_namespace" in bs:
        if not isinstance(bs["user_namespace"], str):
            errors.append("branching_strategy.user_namespace must be a string")
        elif enforce_budget:
            max_len = BRANCHING_STRATEGY_FIELD_MAXLENGTH["user_namespace"]
            if len(bs["user_namespace"]) > max_len:
                errors.append(
                    f"branching_strategy.user_namespace exceeds budget"
                    f" ({len(bs['user_namespace'])} > {max_len} chars)"
                )

    if "protected_branches" in bs:
        pb = bs["protected_branches"]
        if not isinstance(pb, list):
            errors.append("branching_strategy.protected_branches must be a list")
        else:
            for idx, item in enumerate(pb):
                if not isinstance(item, str):
                    errors.append(
                        f"branching_strategy.protected_branches[{idx}] must be a string"
                    )

    if "integration_branch" in bs:
        ib = bs["integration_branch"]
        if ib is not None and not isinstance(ib, str):
            errors.append(
                "branching_strategy.integration_branch must be a string or null"
            )

    if "rationale" in bs:
        if not isinstance(bs["rationale"], str):
            errors.append("branching_strategy.rationale must be a string")
        elif enforce_budget:
            max_len = BRANCHING_STRATEGY_FIELD_MAXLENGTH["rationale"]
            if len(bs["rationale"]) > max_len:
                errors.append(
                    f"branching_strategy.rationale exceeds budget"
                    f" ({len(bs['rationale'])} > {max_len} chars)"
                )

    return errors


def _validate_acceptance_surface_entry(entry: object, idx: int) -> list[str]:
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

    if not isinstance(entry["signals"], list):
        errors.append(f"acceptance_surfaces[{idx}].signals must be a list")
    else:
        for si, sig in enumerate(entry["signals"]):
            if not isinstance(sig, str):
                errors.append(
                    f"acceptance_surfaces[{idx}].signals[{si}] must be a string"
                )

    status = entry["status"]
    if not isinstance(status, str):
        errors.append(f"acceptance_surfaces[{idx}].status must be a string")
    elif status not in _VALID_SURFACE_STATUSES:
        errors.append(
            f"acceptance_surfaces[{idx}].status must be one of"
            f" {sorted(_VALID_SURFACE_STATUSES)} (got {status!r})"
        )

    if "harness" in entry and not isinstance(entry["harness"], str):
        errors.append(f"acceptance_surfaces[{idx}].harness must be a string")

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

    if "branching_strategy" in data:
        errors.extend(
            _validate_branching_strategy(
                data["branching_strategy"], enforce_budget=enforce_budget
            )
        )

    if "acceptance_surfaces" in data:
        surfaces = data["acceptance_surfaces"]
        if not isinstance(surfaces, list):
            errors.append("acceptance_surfaces must be a list")
        else:
            seen_surface_names: set[str] = set()
            for idx, entry in enumerate(surfaces):
                errors.extend(_validate_acceptance_surface_entry(entry, idx))
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    if entry["name"] in seen_surface_names:
                        errors.append(
                            f"acceptance_surfaces[{idx}] duplicate name:"
                            f" {entry['name']!r} — names must be unique"
                        )
                    else:
                        seen_surface_names.add(entry["name"])

    return errors
