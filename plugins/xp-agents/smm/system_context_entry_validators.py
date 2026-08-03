#!/usr/bin/env python3
"""Entry validators + constants for acceptance_surfaces and project_specific lists."""

import json

from schema_helpers import budget_error

PROJECT_SPECIFIC_NAME_MAXLENGTH: int = 50
PROJECT_SPECIFIC_CONTENT_MAXLENGTH: int = 500

ACCEPTANCE_SURFACE_NAME_MAXLENGTH: int = 50
ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH: int = 50
ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH: int = 100
# A surface `paths` entry is a repo-relative glob, so it is bounded by the
# same order of magnitude as a signal string rather than a command.
ACCEPTANCE_SURFACE_PATH_MAXLENGTH: int = 200
# A surface `command` is the same kind of value as `stack.test_command` — a
# narrowed one, not a different species — so it carries the same bound.
# `system_context_schema.STACK_FIELD_MAXLENGTH` holds the other half; they are
# pinned equal by test, since this module cannot import from its own importer.
ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH: int = 100

_ACCEPTANCE_SURFACE_REQUIRED = frozenset({"name", "signals", "status"})
_VALID_SURFACE_STATUSES = frozenset({"covered", "gap"})
ACCEPTANCE_SURFACE_KNOWN_KEYS = frozenset(
    {"name", "signals", "status", "harness", "command", "paths"}
)


def unknown_surface_key_errors(entries: object) -> list[str]:
    """Unrecognized keys on surface entries — for the AUTHORING boundary ONLY.

    Deliberately NOT part of `validate_system_context`. That validator also runs
    on the READ path: `load_system_context` raises on any error, and
    `branching_stage._maybe_auto_promote` performs a load -> mutate -> save
    round-trip from a hook while explicitly not catching ValueError. A
    document-wide unknown-key rule would therefore turn one stray key in a
    project's existing file into a crashed hook the first time its stage
    auto-promotes — punishing users for a typo they may not have made.

    At the add/edit CLI the calculus inverts: a key is being introduced right
    now, by someone who can fix it, and silence there is what lets `cmd` for
    `command` sit in a document selecting nothing forever.

    Takes a LIST of entries. A non-list yields no errors on purpose: for the
    replace-the-whole-array command a bare dict is a SHAPE error, and reporting
    an unknown key there would pre-empt the schema's own message — including
    the null-unset hint that command surfaces for a non-list payload. Callers
    holding a single entry or patch wrap it themselves.
    """
    if not isinstance(entries, list):
        return []
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in sorted(set(entry) - ACCEPTANCE_SURFACE_KNOWN_KEYS):
            errors.append(
                f"unknown acceptance_surface field {key!r} "
                f"(known: {', '.join(sorted(ACCEPTANCE_SURFACE_KNOWN_KEYS))})"
            )
    return errors


# Locked 12-entry convention enum for the optional top-level
# `test_layout` field. The 10 builtin names mirror story-001's
# BUILTIN_LAYOUTS keys; `unknown` is the analyzer's "no marker found"
# state and `custom` lets a customer declare rules-only via `overrides`.
_VALID_TEST_LAYOUT_CONVENTIONS = frozenset(
    {
        "python_pytest",
        "go_native",
        "js_unit",
        "rust_cargo",
        "ruby_rspec",
        "java_junit",
        "csharp_xunit",
        "elixir_exunit",
        "swift_xctest",
        "php_phpunit",
        "unknown",
        "custom",
    }
)

_TEST_LAYOUT_ALLOWED_KEYS = frozenset({"convention", "overrides"})

_OVERRIDE_REQUIRED_STR_KEYS = frozenset(
    {"source_pattern", "stem_extractor", "test_glob"}
)
_OVERRIDE_OPTIONAL_LIST_KEYS = frozenset(
    {"skip_basenames", "skip_suffixes", "source_excludes"}
)
_OVERRIDE_ALLOWED_KEYS = _OVERRIDE_REQUIRED_STR_KEYS | _OVERRIDE_OPTIONAL_LIST_KEYS

# Locked stem-extractor registry. Mirrors STEM_EXTRACTORS in
# plugins/xp-agents/smm/sister_tests.py — the engine layer's pure-discovery
# primitive owns the actual implementations, and the engine schema validates
# declared names against that registry at
# write time. Without this guard a typo'd extractor (e.g. "stem") passes
# schema then raises ValueError inside discover_sister_tests, which the
# sprint_save._auto_include path silently swallows — a silent
# feature-failure on every save. Sync test: test_system_context_schema
# .TestStemExtractorRegistryLock pins these strings against the runtime
# STEM_EXTRACTORS dict, so adding/renaming an extractor breaks the test
# before it can drift.
_VALID_STEM_EXTRACTORS = frozenset({"basename_no_ext"})


def _validate_test_layout_override(entry: object, idx: int) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"test_layout.overrides[{idx}] must be an object"]

    for key in _OVERRIDE_REQUIRED_STR_KEYS:
        if key not in entry:
            errors.append(f"test_layout.overrides[{idx}] missing required field: {key}")
        elif not isinstance(entry[key], str):
            errors.append(f"test_layout.overrides[{idx}].{key} must be a string")

    if (
        isinstance(entry.get("stem_extractor"), str)
        and entry["stem_extractor"] not in _VALID_STEM_EXTRACTORS
    ):
        errors.append(
            f"test_layout.overrides[{idx}].stem_extractor must be one of"
            f" {sorted(_VALID_STEM_EXTRACTORS)} (got {entry['stem_extractor']!r})"
        )

    for key in _OVERRIDE_OPTIONAL_LIST_KEYS:
        if key not in entry:
            continue
        value = entry[key]
        if not isinstance(value, list):
            errors.append(f"test_layout.overrides[{idx}].{key} must be a list")
            continue
        for si, item in enumerate(value):
            if not isinstance(item, str):
                errors.append(
                    f"test_layout.overrides[{idx}].{key}[{si}] must be a string"
                )

    unknown = sorted(set(entry.keys()) - _OVERRIDE_ALLOWED_KEYS)
    if unknown:
        errors.append(
            f"test_layout.overrides[{idx}] has unknown key(s): {unknown}"
            f" (allowed: {sorted(_OVERRIDE_ALLOWED_KEYS)})"
        )

    return errors


def _validate_test_layout(layout: object, *, enforce_budget: bool = True) -> list[str]:
    """Validate the optional top-level test_layout field.

    Returns list of error strings (empty = valid). Never raises.
    Schema: required `convention` in the 12-entry enum, optional
    `overrides` list of dicts (3 required + 3 optional keys each).
    """
    errors: list[str] = []
    if not isinstance(layout, dict):
        return ["test_layout must be an object"]

    if "convention" not in layout:
        errors.append("test_layout missing required field: convention")
        return errors

    convention = layout["convention"]
    if not isinstance(convention, str):
        errors.append("test_layout.convention must be a string")
    elif convention not in _VALID_TEST_LAYOUT_CONVENTIONS:
        errors.append(
            f"test_layout.convention must be one of"
            f" {sorted(_VALID_TEST_LAYOUT_CONVENTIONS)} (got {convention!r})"
        )

    if "overrides" in layout:
        overrides = layout["overrides"]
        if not isinstance(overrides, list):
            errors.append("test_layout.overrides must be a list")
        else:
            for idx, entry in enumerate(overrides):
                errors.extend(_validate_test_layout_override(entry, idx))

    unknown = sorted(set(layout.keys()) - _TEST_LAYOUT_ALLOWED_KEYS)
    if unknown:
        errors.append(
            f"test_layout has unknown key(s): {unknown}"
            f" (allowed: {sorted(_TEST_LAYOUT_ALLOWED_KEYS)})"
        )

    return errors


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

    if "command" in entry:
        if not isinstance(entry["command"], str):
            errors.append(f"acceptance_surfaces[{idx}].command must be a string")
        elif (
            enforce_budget
            and len(entry["command"]) > ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH
        ):
            errors.append(
                budget_error(
                    f"acceptance_surfaces[{idx}].command",
                    len(entry["command"]),
                    ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH,
                )
            )

    if "paths" in entry:
        if not isinstance(entry["paths"], list):
            errors.append(f"acceptance_surfaces[{idx}].paths must be a list")
        else:
            for pi, path in enumerate(entry["paths"]):
                if not isinstance(path, str):
                    errors.append(
                        f"acceptance_surfaces[{idx}].paths[{pi}] must be a string"
                    )
                elif enforce_budget and len(path) > ACCEPTANCE_SURFACE_PATH_MAXLENGTH:
                    errors.append(
                        budget_error(
                            f"acceptance_surfaces[{idx}].paths[{pi}]",
                            len(path),
                            ACCEPTANCE_SURFACE_PATH_MAXLENGTH,
                        )
                    )

    # A command with no paths can never be SELECTED: selection maps a story's
    # file domain onto `paths`, so a pathless surface matches nothing and its
    # command never runs. Declared-but-unreachable reads as configured forever,
    # which is the failure this whole field exists to remove — reject it at
    # write rather than let it look healthy. The reverse is fine: `paths`
    # alone still describes ownership.
    if entry.get("command") and not entry.get("paths"):
        errors.append(
            f"acceptance_surfaces[{idx}].command declared without paths: a surface "
            "with no paths can never be selected, so the command would never run"
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
