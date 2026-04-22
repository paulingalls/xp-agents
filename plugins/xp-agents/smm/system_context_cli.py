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
    system_context_cli.py add-module --smm-dir DIR       < module.json
    system_context_cli.py add-decision --smm-dir DIR     < decision.json
    system_context_cli.py edit-branching --smm-dir DIR   < branching.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import system_context_store as store
from system_context_schema import validate_system_context

_SECTION_HEADINGS: dict[str, str] = {
    "product": "Product",
    "architecture_overview": "Architecture Overview",
    "stack": "Stack",
    "modules": "Modules",
    "conventions": "Conventions",
    "key_decisions": "Key Decisions",
    "sources": "Sources",
    "branching_strategy": "Branching Strategy",
}


def render_markdown(data: dict) -> str:
    """Render a system context dict as markdown."""
    lines: list[str] = []

    lines.append("# System Context")
    lines.append("")

    lines.append("## Product")
    lines.append("")
    lines.append(data["product"])
    lines.append("")

    lines.append("## Architecture Overview")
    lines.append("")
    lines.append(data["architecture_overview"])
    lines.append("")

    _render_stack(lines, data["stack"])
    _render_modules(lines, data["modules"])
    _render_conventions(lines, data["conventions"])
    _render_key_decisions(lines, data["key_decisions"])
    _render_sources(lines, data["sources"])

    for entry in data.get("project_specific", []):
        lines.extend(_render_project_specific(entry))

    if "branching_strategy" in data:
        _render_branching_strategy(lines, data["branching_strategy"])

    return "\n".join(lines)


def _render_stack(lines: list[str], stack: dict) -> None:
    lines.append("## Stack")
    lines.append("")
    if stack.get("languages"):
        lines.append(f"- **Languages:** {', '.join(stack['languages'])}")
    for field in ("runtime", "dependencies_policy", "package_manager"):
        if field in stack:
            heading = field.replace("_", " ").title()
            lines.append(f"- **{heading}:** {stack[field]}")
    lines.append("")


def _render_modules(lines: list[str], modules: list[dict]) -> None:
    lines.append("## Modules")
    lines.append("")
    if not modules:
        lines.append("(none)")
        lines.append("")
        return
    for m in modules:
        count = f" ({m['file_count']} files)" if "file_count" in m else ""
        lines.append(f"- **{m['name']}** (`{m['path']}`){count} — {m['purpose']}")
    lines.append("")


def _render_conventions(lines: list[str], conventions: list[str]) -> None:
    lines.append("## Conventions")
    lines.append("")
    for c in conventions:
        lines.append(f"- {c}")
    lines.append("")


def _render_key_decisions(lines: list[str], decisions: list[dict]) -> None:
    lines.append("## Key Decisions")
    lines.append("")
    for d in decisions:
        rationale = f" — {d['rationale']}" if d.get("rationale") else ""
        lines.append(f"- **{d['topic']}:** {d['decision']}{rationale}")
    lines.append("")


def _render_sources(lines: list[str], sources: list[str]) -> None:
    lines.append("## Sources")
    lines.append("")
    for s in sources:
        lines.append(f"- {s}")
    lines.append("")


_STAGE_NAMES = {
    0: "Stage 0 — Trunk (below plugin floor)",
    1: "Stage 1 — Story branches",
    2: "Stage 2 — Integration",
    3: "Stage 3 — Release flow",
}


def _render_branching_strategy(lines: list[str], bs: dict) -> None:
    lines.append("## Branching Strategy")
    lines.append("")
    stage = bs.get("stage", 0)
    lines.append(f"- **Stage:** {_STAGE_NAMES.get(stage, f'Stage {stage}')}")
    if "user_namespace" in bs:
        lines.append(f"- **User Namespace:** {bs['user_namespace']}")
    if bs.get("protected_branches"):
        branches = ", ".join(f"`{b}`" for b in bs["protected_branches"])
        lines.append(f"- **Protected Branches:** {branches}")
    if bs.get("integration_branch"):
        lines.append(f"- **Integration Branch:** `{bs['integration_branch']}`")
    if bs.get("rationale"):
        lines.append(f"- **Rationale:** {bs['rationale']}")
    lines.append("")


def _render_project_specific(entry: dict) -> list[str]:
    lines: list[str] = []
    lines.append(f"## {entry['name']}")
    lines.append("")

    content = entry["content"]
    if isinstance(content, str):
        lines.append(content)
    elif isinstance(content, list):
        if content and all(isinstance(item, dict) for item in content):
            keys = list(content[0].keys())
            if all(set(item.keys()) == set(keys) for item in content):
                lines.append("| " + " | ".join(keys) + " |")
                lines.append("| " + " | ".join("---" for _ in keys) + " |")
                for item in content:
                    lines.append("| " + " | ".join(str(item[k]) for k in keys) + " |")
            else:
                for item in content:
                    for k, v in item.items():
                        lines.append(f"- **{k}:** {v}")
                    lines.append("")
        else:
            for item in content:
                lines.append(f"- {item}")
    elif isinstance(content, dict):
        for k, v in content.items():
            lines.append(f"- **{k}:** {v}")

    lines.append("")
    return lines


def _render_section(data: dict, name: str) -> str | None:
    if name in _SECTION_HEADINGS:
        lines: list[str] = []
        heading = _SECTION_HEADINGS[name]
        match name:
            case "product" | "architecture_overview":
                lines.append(f"## {heading}")
                lines.append("")
                lines.append(data[name])
                lines.append("")
            case "stack":
                _render_stack(lines, data["stack"])
            case "modules":
                _render_modules(lines, data["modules"])
            case "conventions":
                _render_conventions(lines, data["conventions"])
            case "key_decisions":
                _render_key_decisions(lines, data["key_decisions"])
            case "sources":
                _render_sources(lines, data["sources"])
            case "branching_strategy":
                if "branching_strategy" in data:
                    _render_branching_strategy(lines, data["branching_strategy"])
        return "\n".join(lines)

    for entry in data.get("project_specific", []):
        if entry["name"] == name:
            return "\n".join(_render_project_specific(entry))

    return None


# ── CLI commands ────────────────────────────────────────────────


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
    result = _render_section(data, args.name)
    if result is None:
        print(f"Unknown section: {args.name!r}", file=sys.stderr)
        return 1
    print(result)
    return 0


_OPTIONAL_TOP_LEVEL_FIELDS = frozenset({"branching_strategy"})


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

    if name in data or name in _OPTIONAL_TOP_LEVEL_FIELDS:
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


def _cmd_append_to_list(args: argparse.Namespace, field: str) -> int:
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


def _cmd_add_module(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "modules")


def _cmd_add_decision(args: argparse.Namespace) -> int:
    return _cmd_append_to_list(args, "key_decisions")


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

    sub.add_parser("add-module", help="Add module from stdin JSON")
    sub.add_parser("add-decision", help="Add key decision from stdin JSON")
    sub.add_parser("edit-branching", help="Set branching_strategy from stdin JSON")

    args = parser.parse_args()

    dispatch = {
        "exists": _cmd_exists,
        "validate": _cmd_validate,
        "render": _cmd_render,
        "create": _cmd_create,
        "section": _cmd_section,
        "edit-field": _cmd_edit_field,
        "add-module": _cmd_add_module,
        "add-decision": _cmd_add_decision,
        "edit-branching": _cmd_edit_branching,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
