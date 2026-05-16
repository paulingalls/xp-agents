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
    system_context_cli.py add-principle --smm-dir DIR     < decision.json
    system_context_cli.py add-convention --smm-dir DIR   < convention.json
    system_context_cli.py edit-branching --smm-dir DIR   < branching.json
    system_context_cli.py edit-acceptance-surfaces --smm-dir DIR < surfaces.json
    system_context_cli.py add-acceptance-surface --smm-dir DIR   < surface.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store
from event_metadata import (
    STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE,
    STATUS_ACTION_RETIRE_CONVENTION,
    STATUS_ACTION_RETIRE_MODULE,
    STATUS_ACTION_RETIRE_PRINCIPLE,
    STATUS_ACTION_RETIRE_PROJECT_SPECIFIC,
)
from system_context_renderer import (
    ALL_SECTIONS,
    TOPICS_ONLY_ELIGIBLE,
    render_section,
    render_subset,
)
from system_context_schema import (
    ACCEPTANCE_SURFACES_HARD_CAP,
    ACCEPTANCE_SURFACES_SOFT_CAP,
    CONVENTIONS_HARD_CAP,
    CONVENTIONS_SOFT_CAP,
    MODULES_HARD_CAP,
    MODULES_SOFT_CAP,
    PRINCIPLES_HARD_CAP,
    PRINCIPLES_SOFT_CAP,
    PROJECT_SPECIFIC_HARD_CAP,
    PROJECT_SPECIFIC_SOFT_CAP,
    validate_system_context,
)

_APPEND_SH = Path(__file__).parent / "append.sh"

# Map kind → STATUS_ACTION constant for retire-* status event emission.
# The CLI is a non-hook producer; constants live in event_metadata.py +
# tests/hooks/test_action_vocabulary_smoke.py:_NON_HOOK_PRODUCERS.
_RETIRE_ACTIONS: dict[str, str] = {
    "principle": STATUS_ACTION_RETIRE_PRINCIPLE,
    "module": STATUS_ACTION_RETIRE_MODULE,
    "convention": STATUS_ACTION_RETIRE_CONVENTION,
    "project_specific": STATUS_ACTION_RETIRE_PROJECT_SPECIFIC,
    "acceptance_surface": STATUS_ACTION_RETIRE_ACCEPTANCE_SURFACE,
}

# (soft, hard, retire-subcmd-name) per gated list field. Retire-subcmd
# names forward-reference story-006 — until that ships, the "run
# retire-<kind>" hint points at a command that doesn't yet exist on
# the sprint branch.
_COUNT_CAP_TABLE: dict[str, tuple[int, int, str]] = {
    "modules": (MODULES_SOFT_CAP, MODULES_HARD_CAP, "retire-module"),
    "conventions": (CONVENTIONS_SOFT_CAP, CONVENTIONS_HARD_CAP, "retire-convention"),
    "principles": (PRINCIPLES_SOFT_CAP, PRINCIPLES_HARD_CAP, "retire-principle"),
    "project_specific": (
        PROJECT_SPECIFIC_SOFT_CAP,
        PROJECT_SPECIFIC_HARD_CAP,
        "retire-project-specific",
    ),
    "acceptance_surfaces": (
        ACCEPTANCE_SURFACES_SOFT_CAP,
        ACCEPTANCE_SURFACES_HARD_CAP,
        "retire-acceptance-surface",
    ),
}

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

    caps = _COUNT_CAP_TABLE.get(field)
    bucket = data.setdefault(field, []) if create_if_missing else data[field]

    if caps is not None:
        _, hard, retire_cmd = caps
        if len(bucket) >= hard:
            print(
                f"{field} hard cap reached ({len(bucket)}/{hard}); "
                f"run {retire_cmd} first",
                file=sys.stderr,
            )
            return 1

    bucket.append(item)
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1

    if caps is not None:
        soft, hard, _ = caps
        if len(bucket) >= soft:
            print(
                f"{field} approaching cap ({len(bucket)}/{hard})",
                file=sys.stderr,
            )

    return 0


def _cmd_edit_branching(args: argparse.Namespace) -> int:
    args.name = "branching_strategy"
    return _cmd_edit_field(args)


def _cmd_edit_branching_field(args: argparse.Namespace) -> int:
    """Set or clear an optional field nested under branching_strategy.

    Mirrors edit-stack-field: top-level edit-field can't reach nested
    keys, and rewriting the whole branching_strategy via edit-branching
    would force the caller to re-supply stage and any other already-set
    fields. This narrow path edits one nested field at a time and lets
    the schema validator catch typos (unknown field, value too long,
    wrong type/format).

    Reads the new value from stdin as JSON. Pass ``null`` to clear.

    Side-effect: when the system_context lacks branching_strategy
    entirely, the CLI seeds it with ``{"stage": 0}`` before applying
    the edit (mirrors edit-branching). Pre-seeding lets the validator
    accept the result; the caller can then bump stage explicitly via
    edit-branching if needed.
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

    bs = data.setdefault("branching_strategy", {"stage": 0})
    if value is None:
        bs.pop(args.name, None)
    else:
        bs[args.name] = value

    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_get_branching_field(args: argparse.Namespace) -> int:
    """Print the value of a nested branching_strategy field, or empty
    string if unset. Read-only counterpart to edit-branching-field.

    Exits 0 with empty stdout when system_context.json is missing OR
    the field is unset — that uniform "absent → empty" signal lets
    shell callers plug the value into ``KEY=$(...)`` without exit-code
    branching. Mirrors get-stack-field.

    Used by xp-kickoff Step 2.4 to read stage_prompt_dismissed_at and
    skip the migration prompt while the dismissal is in effect.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("")
        return 0
    val = data.get("branching_strategy", {}).get(args.name)
    print(val if val is not None else "")
    return 0


def _cmd_get_stack_field(args: argparse.Namespace) -> int:
    """Print the value of a nested stack field, or empty string if unset.

    Read-only counterpart to `edit-stack-field`. Exits 0 with empty
    stdout when system_context.json is missing OR the field is unset —
    that uniform "absent → empty" signal lets shell callers plug the
    value into `KEY=$(...)` without exit-code branching.

    Schema-invalid files (e.g., a hand-edit that set test_command to a
    non-string) surface as a load-time ValueError; we let that propagate
    so the user gets a real traceback. The shell wrapper
    `_preload_base.sh:find_test_command` traps that via
    `2>/dev/null || echo ""` so the close-skill preload still emits
    TEST_COMMAND= (empty) and falls through to the discovery hint —
    but the failure isn't silenced at the CLI layer.

    Used by `_preload_base.sh:find_test_command` to source the project's
    test command for the story-close + free-close auto-merge gate.
    """
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("")
        return 0
    print(data.get("stack", {}).get(args.name, ""))
    return 0


def _cmd_edit_stack_field(args: argparse.Namespace) -> int:
    """Set or clear an optional field nested under stack (e.g. test_command).

    Top-level edit-field can't reach nested keys, and rewriting the whole
    stack via edit-field would force the caller to re-supply languages
    and other already-set fields. This narrow path edits one nested
    field at a time and lets the schema validator catch typos
    (unknown stack field, value too long, wrong type).

    Reads the new value from stdin as JSON. Pass `null` to clear.

    Side-effect: when the system_context lacks stack entirely, the CLI
    seeds it with ``{"languages": []}`` before applying the edit.
    Pre-seeding lets the validator accept the result; the caller can
    populate languages explicitly via edit-field if needed.
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


def _cmd_add_principle(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "principles")


def _emit_retire_event(smm_dir: Path, kind: str, identifier: str) -> None:
    """Append a status event recording the retire-* action."""
    metadata = json.dumps(
        {"action": _RETIRE_ACTIONS[kind], "kind": kind, "identifier": identifier}
    )
    subprocess.run(
        [
            str(_APPEND_SH),
            "--smm-dir",
            str(smm_dir),
            "--type",
            "status",
            "--agent",
            "system-context-cli",
            "--content",
            f"retired {kind} {identifier}",
            "--working-on",
            "[]",
            "--metadata",
            metadata,
        ],
        check=True,
    )


def _cmd_retire_by_key(
    args: argparse.Namespace, field: str, key_field: str, kind: str
) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get(field, [])
    for i, entry in enumerate(bucket):
        if entry.get(key_field) == args.identifier:
            del bucket[i]
            try:
                store.save_system_context(args.smm_dir, data)
            except ValueError as exc:
                print(f"Validation error: {exc}", file=sys.stderr)
                return 1
            _emit_retire_event(args.smm_dir, kind, args.identifier)
            return 0
    print(
        f"{field}[{key_field}={args.identifier!r}] not found",
        file=sys.stderr,
    )
    return 1


def _cmd_retire_principle(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "principles", "topic", "principle")


def _cmd_retire_module(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "modules", "name", "module")


def _cmd_retire_project_specific(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "project_specific", "name", "project_specific")


def _cmd_retire_acceptance_surface(args: argparse.Namespace) -> int:
    return _cmd_retire_by_key(args, "acceptance_surfaces", "name", "acceptance_surface")


def _cmd_retire_convention(args: argparse.Namespace) -> int:
    data = store.load_system_context(args.smm_dir)
    if data is None:
        print("No system context found.", file=sys.stderr)
        return 1
    bucket = data.get("conventions", [])
    identifier = args.identifier

    if identifier.isdigit():
        idx = int(identifier)
        if idx < 0 or idx >= len(bucket):
            print(
                f"conventions[{idx}] out of range (have {len(bucket)} entries)",
                file=sys.stderr,
            )
            return 1
        resolved = bucket[idx]
    else:
        matches = [i for i, c in enumerate(bucket) if identifier in c]
        if not matches:
            print(
                f"conventions: no match for substring {identifier!r}",
                file=sys.stderr,
            )
            return 1
        if len(matches) > 1:
            preview = "; ".join(bucket[i] for i in matches)
            print(
                f"conventions: ambiguous substring {identifier!r} "
                f"({len(matches)} matches): {preview}",
                file=sys.stderr,
            )
            return 1
        idx = matches[0]
        resolved = bucket[idx]

    del bucket[idx]
    try:
        store.save_system_context(args.smm_dir, data)
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 1
    _emit_retire_event(args.smm_dir, "convention", resolved)
    return 0


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
    sub.add_parser("add-principle", help="Add principle from stdin JSON")
    sub.add_parser("add-convention", help="Add convention from stdin JSON")
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

    for name, help_text in (
        ("retire-principle", "Retire a principle by topic"),
        ("retire-module", "Retire a module by name"),
        ("retire-convention", "Retire a convention by index or substring"),
        ("retire-project-specific", "Retire a project_specific entry by name"),
        ("retire-acceptance-surface", "Retire an acceptance surface by name"),
    ):
        retire_p = sub.add_parser(name, help=help_text)
        retire_p.add_argument("identifier", help="topic/name/index/substring")

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
        "add-principle": _cmd_add_principle,
        "add-convention": _cmd_add_convention,
        "edit-acceptance-surfaces": _cmd_edit_acceptance_surfaces,
        "add-acceptance-surface": _cmd_add_acceptance_surface,
        "edit-branching": _cmd_edit_branching,
        "edit-branching-field": _cmd_edit_branching_field,
        "get-branching-field": _cmd_get_branching_field,
        "retire-principle": _cmd_retire_principle,
        "retire-module": _cmd_retire_module,
        "retire-convention": _cmd_retire_convention,
        "retire-project-specific": _cmd_retire_project_specific,
        "retire-acceptance-surface": _cmd_retire_acceptance_surface,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
