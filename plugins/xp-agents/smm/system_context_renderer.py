#!/usr/bin/env python3
"""Markdown rendering for system_context dicts.

Pure functions — no I/O, no side effects. Takes a validated dict, returns a
markdown string. Extracted out of `system_context_cli.py` once that file
crossed the 500-line ceiling. Two public entry points:

- `render_markdown(data)` — full document rendering. Used by the CLI's
  `render` subcommand and by `scripts/session_start.py` to surface the
  curated context at session start.
- `render_section(data, name)` — single-section rendering. Used by the
  CLI's `section` subcommand. Returns `None` when the requested name is
  unknown so the caller can distinguish "no such section" from "empty
  section".

Per-section formatters stay private (`_render_*`) — they're internal
helpers that take a list-of-lines accumulator and append. Refactor
candidates move together; keeping them adjacent and private makes that
move cheap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from system_context_schema import STACK_OPTIONAL_FIELDS

_SECTION_HEADINGS: dict[str, str] = {
    "product": "Product",
    "architecture_overview": "Architecture Overview",
    "stack": "Stack",
    "modules": "Modules",
    "conventions": "Conventions",
    "key_decisions": "Key Decisions",
    "sources": "Sources",
    "branching_strategy": "Branching Strategy",
    "acceptance_surfaces": "Acceptance Surfaces",
}

_STAGE_NAMES = {
    0: "Stage 0 — Trunk (below plugin floor)",
    1: "Stage 1 — Story branches",
    2: "Stage 2 — Integration",
    3: "Stage 3 — Release flow",
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

    if "acceptance_surfaces" in data:
        _render_acceptance_surfaces(lines, data["acceptance_surfaces"])

    return "\n".join(lines)


def render_section(data: dict, name: str) -> str | None:
    """Render one named section. Returns None when name is unknown.

    Looks up the section first in `_SECTION_HEADINGS` (the canonical
    pillars), then in `data["project_specific"]` (custom entries). The
    None return distinguishes "no such section" from "section is empty"
    so CLI callers can exit non-zero on the former.
    """
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
            case "acceptance_surfaces":
                if "acceptance_surfaces" in data:
                    _render_acceptance_surfaces(lines, data["acceptance_surfaces"])
        return "\n".join(lines)

    for entry in data.get("project_specific", []):
        if entry["name"] == name:
            return "\n".join(_render_project_specific(entry))

    return None


def _render_stack(lines: list[str], stack: dict) -> None:
    lines.append("## Stack")
    lines.append("")
    if stack.get("languages"):
        lines.append(f"- **Languages:** {', '.join(stack['languages'])}")
    for field in STACK_OPTIONAL_FIELDS:
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


def _render_acceptance_surfaces(lines: list[str], surfaces: list[dict]) -> None:
    lines.append("## Acceptance Surfaces")
    lines.append("")
    if not surfaces:
        lines.append("(none)")
        lines.append("")
        return
    for s in surfaces:
        harness = f" [{s['harness']}]" if s.get("harness") else ""
        signals = ", ".join(s.get("signals", []))
        signals_str = f" — {signals}" if signals else ""
        lines.append(f"- **{s['name']}** ({s['status']}){harness}{signals_str}")
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
