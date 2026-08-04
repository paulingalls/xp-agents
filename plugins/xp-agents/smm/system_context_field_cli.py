#!/usr/bin/env python3
"""The whole-document `create` and generic `edit-field` commands, the
optional-field set they share, and the per-field authoring checks both apply.

Extracted from system_context_cli.py at the commit that pushed it over the
500-line cap. `_OPTIONAL_TOP_LEVEL_FIELDS` travels with these two because they
are its only implementers — `edit-field` the null-unset half, `create` the
preserve-or-drop half. `_FIELD_VALUE_CHECKS` keys authoring checks on the FIELD
so both doors inherit them. system_context_cli re-exports all three, so every
existing import path and `mock.patch` target keeps resolving.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store
from system_context_entry_validators import unknown_surface_key_errors

# Optional top-level fields: absent is legal, and stdin `null` UNSETS them
# rather than storing a null.
_OPTIONAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "branching_strategy",
        "acceptance_surfaces",
        "test_layout",
    }
)

# Authoring checks that belong to the FIELD, not to one command. `edit-field
# <name>` reaches this same writer that the named `edit-<field>` commands
# delegate to, so keying the check on the field closes the generic door too —
# hanging it off the named command alone would leave `edit-field
# acceptance_surfaces` as a silent bypass of the very check it mirrors.
_FIELD_VALUE_CHECKS: dict[str, Callable[[object], list[str]]] = {
    "acceptance_surfaces": unknown_surface_key_errors,
}


def _cmd_create(args: argparse.Namespace) -> int:
    """Write the whole document from stdin JSON.

    Lives beside `edit-field` because the two implement the SAME optional-field
    contract from opposite ends: `edit-field` owns the null-unset half, `create`
    owns preserve-or-drop. Splitting them across modules is how one half drifts.
    """
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    # `create` is where surfaces are FIRST authored — the analyzer is told to
    # inline them here and NOT to patch them separately in create mode, so
    # leaving the check to the edit/add doors alone would miss the one moment
    # the field names get typed for the first time. Only the payload's own
    # surfaces are checked; ones preserved from an existing document below are
    # grandfathered, exactly as the read path is.
    for field, check in _FIELD_VALUE_CHECKS.items():
        problems = check(data.get(field) if isinstance(data, dict) else None)
        if problems:
            print("; ".join(problems), file=sys.stderr)
            return 1

    if isinstance(data, dict) and any(
        f not in data or data[f] is None for f in _OPTIONAL_TOP_LEVEL_FIELDS
    ):
        existing = store.load_system_context(args.smm_dir) or {}
        for field in _OPTIONAL_TOP_LEVEL_FIELDS:
            if field in data and data[field] is None:
                del data[field]
            elif field not in data and field in existing:
                data[field] = existing[field]
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_edit_field(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1

    name = args.name
    if (
        name not in data
        and name != "project_specific"
        and name not in _OPTIONAL_TOP_LEVEL_FIELDS
    ):
        ps_names = [e["name"] for e in data.get("project_specific", [])]
        if name not in ps_names:
            print(f"Unknown field: {name!r}", file=sys.stderr)
            return 1

    raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    value_check = _FIELD_VALUE_CHECKS.get(name)
    if value_check is not None:
        problems = value_check(value)
        if problems:
            print("; ".join(problems), file=sys.stderr)
            return 1

    # edit-field is single-field; only the null-wipe half of _cmd_create's
    # optional-field contract applies — preservation isn't relevant when
    # the caller is targeting one specific field.
    if name in _OPTIONAL_TOP_LEVEL_FIELDS and value is None:
        data.pop(name, None)
    elif name in data or name in _OPTIONAL_TOP_LEVEL_FIELDS:
        data[name] = value
    else:
        for entry in data.get("project_specific", []):
            if entry["name"] == name:
                entry["content"] = value
                break

    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        # Optional top-level fields can be unset with stdin `null`; surface
        # that affordance when a non-null edit fails validation, so future
        # optional fields inherit the same UX without per-command duplication.
        if name in _OPTIONAL_TOP_LEVEL_FIELDS:
            print(
                f"{name} can be unset by passing `null` on stdin.",
                file=sys.stderr,
            )
        return 1
    return 0
