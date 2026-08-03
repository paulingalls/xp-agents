#!/usr/bin/env python3
"""The generic top-level `edit-field` command and the optional-field set.

Extracted from system_context_cli.py at the commit that pushed it over the
500-line cap. `edit-field` is an EDIT command that had been living in the
aggregator; `_OPTIONAL_TOP_LEVEL_FIELDS` travels with it because the
null-unset affordance the command implements is the reason that set exists.
system_context_cli re-exports both, so every existing import path and
`mock.patch` target keeps resolving.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store

# Optional top-level fields: absent is legal, and stdin `null` UNSETS them
# rather than storing a null.
_OPTIONAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "branching_strategy",
        "acceptance_surfaces",
        "test_layout",
    }
)


def _cmd_edit_field(
    args: argparse.Namespace,
    *,
    value_check: Callable[[object], list[str]] | None = None,
) -> int:
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
