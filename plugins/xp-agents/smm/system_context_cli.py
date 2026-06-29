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
    system_context_cli.py get-stack-field NAME --smm-dir DIR
    system_context_cli.py add-module --smm-dir DIR       < module.json
    system_context_cli.py add-convention --smm-dir DIR   < convention.json
    system_context_cli.py add-principle --smm-dir DIR     < decision.json
    system_context_cli.py add-project-specific --smm-dir DIR < entry.json
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
from system_context_caps_cli import (
    _COUNT_CAP_TABLE,
)
from system_context_caps_cli import (
    cmd_append_to_list as _cmd_append_to_list,
)
from system_context_edit_cli import (
    _EDIT_ACTIONS,
    _emit_edit_event,
)
from system_context_edit_cli import (
    cmd_edit_acceptance_surface as _cmd_edit_acceptance_surface,
)
from system_context_edit_cli import (
    cmd_edit_convention as _cmd_edit_convention,
)
from system_context_edit_cli import (
    cmd_edit_module as _cmd_edit_module,
)
from system_context_edit_cli import (
    cmd_edit_principle as _cmd_edit_principle,
)
from system_context_edit_cli import (
    cmd_edit_project_specific as _cmd_edit_project_specific,
)
from system_context_entry_validators import _validate_test_layout
from system_context_nested_field_cli import (
    cmd_edit_branching_field as _cmd_edit_branching_field,
)
from system_context_nested_field_cli import (
    cmd_edit_stack_field as _cmd_edit_stack_field,
)
from system_context_nested_field_cli import (
    cmd_get_branching_field as _cmd_get_branching_field,
)
from system_context_nested_field_cli import (
    cmd_get_stack_field as _cmd_get_stack_field,
)
from system_context_renderer import (
    ALL_SECTIONS,
    TOPICS_ONLY_ELIGIBLE,
    render_section,
    render_subset,
)
from system_context_retire_cli import (
    _RETIRE_ACTIONS,
    _emit_retire_event,
)
from system_context_retire_cli import (
    cmd_retire_acceptance_surface as _cmd_retire_acceptance_surface,
)
from system_context_retire_cli import (
    cmd_retire_convention as _cmd_retire_convention,
)
from system_context_retire_cli import (
    cmd_retire_module as _cmd_retire_module,
)
from system_context_retire_cli import (
    cmd_retire_principle as _cmd_retire_principle,
)
from system_context_retire_cli import (
    cmd_retire_project_specific as _cmd_retire_project_specific,
)
from system_context_schema import validate_system_context

# Back-compat shim: callers that imported these names from
# system_context_cli before each family was extracted still find them
# here. __all__ both documents the shim surface and quiets ruff's
# unused-import lint on the re-export imports. The shim identity
# contract (same function object across modules) is pinned by per-
# extracted-module reimport tests.
__all__ = [
    "_COUNT_CAP_TABLE",
    "_EDIT_ACTIONS",
    "_RETIRE_ACTIONS",
    "_cmd_append_to_list",
    "_cmd_edit_branching_field",
    "_cmd_edit_stack_field",
    "_cmd_get_branching_field",
    "_cmd_get_stack_field",
    "_emit_edit_event",
    "_emit_retire_event",
]

# ── CLI commands ────────────────────────────────────────────────


_OPTIONAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "branching_strategy",
        "acceptance_surfaces",
        "test_layout",
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

    sections = _split_csv(args.sections) if args.sections else None
    topics_only = _split_csv(args.topics_only) if args.topics_only else None

    if topics_only and not sections:
        print(
            "--topics-only requires --sections (each topics-only name must "
            "also appear in --sections)",
            file=sys.stderr,
        )
        return 1

    if sections:
        unknown = [s for s in sections if s not in ALL_SECTIONS]
        if unknown:
            print(
                f"Unknown section(s): {', '.join(unknown)}. Valid: "
                f"{', '.join(ALL_SECTIONS)}",
                file=sys.stderr,
            )
            return 1

    if topics_only:
        ineligible = [t for t in topics_only if t not in TOPICS_ONLY_ELIGIBLE]
        if ineligible:
            print(
                f"--topics-only not supported for: {', '.join(ineligible)}. "
                f"Eligible: {', '.join(sorted(TOPICS_ONLY_ELIGIBLE))}",
                file=sys.stderr,
            )
            return 1
        missing = [t for t in topics_only if t not in (sections or [])]
        if missing:
            print(
                f"--topics-only names must also appear in --sections: "
                f"{', '.join(missing)}",
                file=sys.stderr,
            )
            return 1

    print(render_subset(data, sections=sections, topics_only=topics_only))
    return 0


def _split_csv(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


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


def _cmd_edit_branching(args: argparse.Namespace) -> int:
    args.name = "branching_strategy"
    return _cmd_edit_field(args)


def _cmd_add_module(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "modules")


def _cmd_add_convention(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "conventions")


def _cmd_add_principle(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "principles")


def _cmd_add_project_specific(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "project_specific")


def _cmd_edit_acceptance_surfaces(args: argparse.Namespace) -> int:
    args.name = "acceptance_surfaces"
    return _cmd_edit_field(args)


def _cmd_add_acceptance_surface(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "acceptance_surfaces", create_if_missing=True)


def _cmd_edit_test_layout(args: argparse.Namespace) -> int:
    """Set test_layout from stdin JSON.

    - stdin `null` → unset the field (idempotent).
    - stdin valid layout object → write atomically.
    - stdin `{}` (or any other invalid shape) → reject; the validator
      surfaces "missing required field: convention" and the CLI prints
      a stderr hint pointing at the unset path.
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

    if value is None:
        data.pop("test_layout", None)
    else:
        errors = _validate_test_layout(value)
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            print(
                "test_layout requires `convention`; pass `null` to unset.",
                file=sys.stderr,
            )
            return 1
        data["test_layout"] = value

    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_get_test_layout(args: argparse.Namespace) -> int:
    """Print the current test_layout as JSON (or `null` when absent)."""
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    print(json.dumps(data.get("test_layout")))
    return 0


# ── main ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="System context CLI")
    parser.add_argument(
        "--smm-dir", type=Path, required=True, help="SMM directory path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("exists", help="Check if system context exists")
    sub.add_parser("validate", help="Validate system context")
    render_p = sub.add_parser("render", help="Render as markdown")
    render_p.add_argument(
        "--sections",
        help="Comma-separated section names to render (default: all)",
    )
    render_p.add_argument(
        "--topics-only",
        help=(
            "Comma-separated subset of --sections to render as identifier "
            "bullets only (eligible: principles, project_specific)"
        ),
    )
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

    get_stack_p = sub.add_parser(
        "get-stack-field",
        help="Print a nested stack field's value (or empty if unset)",
    )
    get_stack_p.add_argument("name", help="Stack field name (e.g. test_command)")

    sub.add_parser("add-module", help="Add module from stdin JSON")
    sub.add_parser("add-convention", help="Add convention from stdin JSON")
    sub.add_parser("add-principle", help="Add principle from stdin JSON")
    sub.add_parser(
        "add-project-specific", help="Add project_specific entry from stdin JSON"
    )
    sub.add_parser("edit-branching", help="Set branching_strategy from stdin JSON")

    edit_branching_field_p = sub.add_parser(
        "edit-branching-field",
        help="Edit a nested branching_strategy field from stdin JSON",
    )
    edit_branching_field_p.add_argument(
        "name", help="Branching strategy field name (e.g. stage_prompt_dismissed_at)"
    )

    get_branching_field_p = sub.add_parser(
        "get-branching-field",
        help="Print a nested branching_strategy field's value (or empty if unset)",
    )
    get_branching_field_p.add_argument(
        "name", help="Branching strategy field name (e.g. stage_prompt_dismissed_at)"
    )
    sub.add_parser(
        "edit-acceptance-surfaces",
        help="Set acceptance_surfaces from stdin JSON",
    )
    sub.add_parser(
        "add-acceptance-surface",
        help="Add one acceptance surface from stdin JSON",
    )
    sub.add_parser(
        "edit-test-layout",
        help=("Set test_layout from stdin JSON (stdin `null` unsets the field)"),
    )
    sub.add_parser(
        "get-test-layout",
        help="Print test_layout as JSON (or `null` when unset)",
    )

    for name, help_text in (
        ("retire-principle", "Retire a principle by topic"),
        ("retire-module", "Retire a module by name"),
        ("retire-convention", "Retire a convention by index or substring"),
        ("retire-project-specific", "Retire a project_specific entry by name"),
        ("retire-acceptance-surface", "Retire an acceptance surface by name"),
    ):
        retire_p = sub.add_parser(name, help=help_text)
        retire_p.add_argument("identifier", help="topic/name/index/substring")

    for name, help_text in (
        (
            "edit-principle",
            "Edit a principle by topic; stdin is JSON patch (null value clears a key)",
        ),
        (
            "edit-module",
            "Edit a module by name; stdin is JSON patch (null value clears a key)",
        ),
        (
            "edit-convention",
            "Edit a convention by index or substring; stdin is JSON-encoded string",
        ),
        (
            "edit-project-specific",
            "Edit a project_specific entry by name; stdin is JSON patch "
            "(null value clears a key)",
        ),
        (
            "edit-acceptance-surface",
            "Edit an acceptance surface by name; stdin is JSON patch "
            "(null value clears a key)",
        ),
    ):
        edit_p = sub.add_parser(name, help=help_text)
        edit_p.add_argument("identifier", help="topic/name/index/substring")

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "validate": _cmd_validate,
        "render": _cmd_render,
        "create": _cmd_create,
        "section": _cmd_section,
        "edit-field": _cmd_edit_field,
        "edit-stack-field": _cmd_edit_stack_field,
        "get-stack-field": _cmd_get_stack_field,
        "add-module": _cmd_add_module,
        "add-convention": _cmd_add_convention,
        "add-principle": _cmd_add_principle,
        "add-project-specific": _cmd_add_project_specific,
        "edit-acceptance-surfaces": _cmd_edit_acceptance_surfaces,
        "add-acceptance-surface": _cmd_add_acceptance_surface,
        "edit-test-layout": _cmd_edit_test_layout,
        "get-test-layout": _cmd_get_test_layout,
        "edit-branching": _cmd_edit_branching,
        "edit-branching-field": _cmd_edit_branching_field,
        "get-branching-field": _cmd_get_branching_field,
        "retire-principle": _cmd_retire_principle,
        "retire-module": _cmd_retire_module,
        "retire-convention": _cmd_retire_convention,
        "retire-project-specific": _cmd_retire_project_specific,
        "retire-acceptance-surface": _cmd_retire_acceptance_surface,
        "edit-principle": _cmd_edit_principle,
        "edit-module": _cmd_edit_module,
        "edit-convention": _cmd_edit_convention,
        "edit-project-specific": _cmd_edit_project_specific,
        "edit-acceptance-surface": _cmd_edit_acceptance_surface,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
