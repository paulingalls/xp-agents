#!/usr/bin/env python3
"""CLI for system context operations.

Thin wrapper over system_context_store.py for shell scripts and
Claude Code skills. Python scripts should import the store directly.

Usage:
    system_context_cli.py exists --smm-dir DIR
    system_context_cli.py validate --smm-dir DIR
    system_context_cli.py render --smm-dir DIR
    system_context_cli.py create --smm-dir DIR          < context.json
    system_context_cli.py section NAME --smm-dir DIR
    system_context_cli.py edit-field NAME --smm-dir DIR  < value.json
    system_context_cli.py edit-stack-field NAME --smm-dir DIR  < value.json
    system_context_cli.py add-module --smm-dir DIR       < module.json
    system_context_cli.py add-decision --smm-dir DIR     < decision.json
    system_context_cli.py add-convention --smm-dir DIR   < convention.json
    system_context_cli.py edit-branching --smm-dir DIR   < branching.json
    system_context_cli.py edit-acceptance-surfaces --smm-dir DIR < surfaces.json
    system_context_cli.py add-acceptance-surface --smm-dir DIR   < surface.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store
from system_context_renderer import render_markdown, render_section
from system_context_schema import validate_system_context

# ── CLI commands ────────────────────────────────────────────────


_OPTIONAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "branching_strategy",
        "acceptance_surfaces",
    }
)


def _cmd_exists(args: argparse.Namespace) -> int:
    return 0 if store.system_context_exists(args.smm_dir) else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    errors = validate_system_context(data)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    print(render_markdown(data))
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
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


def _cmd_section(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    result = render_section(data, args.name)
    if result is None:
        print(f"Unknown section: {args.name!r}", file=sys.stderr)
        return 1
    print(result)
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
        return 1
    return 0


def _cmd_append_to_list(
    args: argparse.Namespace, field: str, *, create_if_missing: bool = False
) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    raw = sys.stdin.read()
    try:
        item = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1
    if create_if_missing:
        data.setdefault(field, []).append(item)
    else:
        data[field].append(item)
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_edit_branching(args: argparse.Namespace) -> int:
    args.name = "branching_strategy"
    return _cmd_edit_field(args)


def _cmd_edit_stack_field(args: argparse.Namespace) -> int:
    """Set or clear an optional field nested under stack (e.g. test_command).

    Top-level edit-field can't reach nested keys, and rewriting the whole
    stack via edit-field would force the caller to re-supply languages
    and other already-set fields. This narrow path edits one nested
    field at a time and lets the schema validator catch typos
    (unknown stack field, value too long, wrong type).

    Reads the new value from stdin as JSON. Pass `null` to clear.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1

    raw = sys.stdin.read()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        return 1

    stack = data.setdefault("stack", {"languages": []})
    if value is None:
        stack.pop(args.name, None)
    else:
        stack[args.name] = value

    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_add_module(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "modules")


def _cmd_add_convention(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "conventions")


def _cmd_add_decision(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "key_decisions")


def _cmd_edit_acceptance_surfaces(args: argparse.Namespace) -> int:
    args.name = "acceptance_surfaces"
    return _cmd_edit_field(args)


def _cmd_add_acceptance_surface(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "acceptance_surfaces", create_if_missing=True)


# ── main ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="System context CLI")
    parser.add_argument(
        "--smm-dir", type=Path, required=True, help="SMM directory path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("exists", help="Check if system context exists")
    sub.add_parser("validate", help="Validate system context")
    sub.add_parser("render", help="Render as markdown")
    sub.add_parser("create", help="Create from stdin JSON")

    section_p = sub.add_parser("section", help="Render one section")
    section_p.add_argument("name", help="Section name")

    edit_p = sub.add_parser("edit-field", help="Edit a field from stdin JSON")
    edit_p.add_argument("name", help="Field name")

    edit_stack_p = sub.add_parser(
        "edit-stack-field",
        help="Edit a nested stack field from stdin JSON (e.g. test_command)",
    )
    edit_stack_p.add_argument("name", help="Stack field name (e.g. test_command)")

    sub.add_parser("add-module", help="Add module from stdin JSON")
    sub.add_parser("add-decision", help="Add key decision from stdin JSON")
    sub.add_parser("add-convention", help="Add convention from stdin JSON")
    sub.add_parser("edit-branching", help="Set branching_strategy from stdin JSON")
    sub.add_parser(
        "edit-acceptance-surfaces",
        help="Set acceptance_surfaces from stdin JSON",
    )
    sub.add_parser(
        "add-acceptance-surface",
        help="Add one acceptance surface from stdin JSON",
    )

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "validate": _cmd_validate,
        "render": _cmd_render,
        "create": _cmd_create,
        "section": _cmd_section,
        "edit-field": _cmd_edit_field,
        "edit-stack-field": _cmd_edit_stack_field,
        "add-module": _cmd_add_module,
        "add-decision": _cmd_add_decision,
        "add-convention": _cmd_add_convention,
        "edit-acceptance-surfaces": _cmd_edit_acceptance_surfaces,
        "add-acceptance-surface": _cmd_add_acceptance_surface,
        "edit-branching": _cmd_edit_branching,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
