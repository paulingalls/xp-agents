#!/usr/bin/env python3
"""Markdown rendering for system_context dicts.

Pure functions — no I/O, no side effects. Takes a validated dict, returns a
markdown string. Extracted out of `system_context_cli.py` once that file
crossed the 500-line ceiling. One internal entry point with two thin
public wrappers:

- `render_subset(data, sections, topics_only)` — selectable rendering.
  Iterates canonical section order, filters by `sections`, collapses
  identifier-only sections to TOC bullets when listed in `topics_only`.
- `render_markdown(data)` — thin wrapper: `render_subset(data)` with no
  filters. Used by the CLI's `render` subcommand (no flags) and by
  `scripts/session_start.py` to surface the curated context at session
  start.
- `render_section(data, name)` — single-section wrapper. Used by the
  CLI's `section` subcommand. Returns `None` when the requested name is
  unknown (neither a canonical section nor a `project_specific` entry
  name) so the caller can distinguish "no such section" from "empty
  section".

Per-section formatters stay private (`_render_*`) — they're internal
helpers that take a list-of-lines accumulator and append.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from execution_plan_schema import usable_git_ref_name
from system_context_schema import STACK_OPTIONAL_FIELDS, healed_user_namespace

_SECTION_HEADINGS: dict[str, str] = {
    "product": "Product",
    "architecture_overview": "Architecture Overview",
    "stack": "Stack",
    "modules": "Modules",
    "conventions": "Conventions",
    "principles": "Principles",
    "branching_strategy": "Branching Strategy",
    "acceptance_surfaces": "Acceptance Surfaces",
    "test_layout": "Test Layout",
}

_STAGE_NAMES = {
    0: "Stage 0 — Trunk (below plugin floor)",
    1: "Stage 1 — Story branches",
    2: "Stage 2 — Integration",
    3: "Stage 3 — Release flow",
}

# Canonical render order. `project_specific` is a renderable section
# (renders all entries) but lives outside `_SECTION_HEADINGS` because
# the entries have their own `name`-keyed headings.
ALL_SECTIONS: tuple[str, ...] = (
    "product",
    "architecture_overview",
    "stack",
    "modules",
    "conventions",
    "principles",
    "project_specific",
    "branching_strategy",
    "acceptance_surfaces",
    "test_layout",
)

# Sections whose items carry an identifier field (`topic` / `name`)
# that can be collapsed to a TOC-style bullet list via --topics-only.
TOPICS_ONLY_ELIGIBLE: frozenset[str] = frozenset({"principles", "project_specific"})


def render_subset(
    data: dict,
    sections: list[str] | None = None,
    topics_only: list[str] | None = None,
    include_doc_header: bool = True,
) -> str:
    """Render selected sections of a system context dict as markdown.

    `sections=None` renders all canonical sections. Iteration order is
    always canonical (see `ALL_SECTIONS`), regardless of the order in
    the caller's list — output is stable across callers.

    `topics_only` names a subset of `sections`; each listed section is
    collapsed to a TOC of identifier bullets (`topic` for principles,
    `name` for project_specific). Only items in `TOPICS_ONLY_ELIGIBLE`
    are valid; ineligible names raise ValueError so misuse is loud, not
    silent — the CLI also validates upfront to surface argparse-style
    errors before reaching here.

    `include_doc_header=False` omits the leading "# System Context"
    document header — used by `render_section` so single-section output
    starts at the section heading.
    """
    sections_set = set(sections) if sections else set(ALL_SECTIONS)
    topics_set = set(topics_only or [])
    ineligible = topics_set - TOPICS_ONLY_ELIGIBLE
    if ineligible:
        raise ValueError(
            f"topics_only not supported for: {sorted(ineligible)}. "
            f"Eligible: {sorted(TOPICS_ONLY_ELIGIBLE)}"
        )

    lines: list[str] = ["# System Context", ""] if include_doc_header else []

    for name in ALL_SECTIONS:
        if name not in sections_set:
            continue
        match name:
            case "product" | "architecture_overview":
                heading = _SECTION_HEADINGS[name]
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
            case "principles":
                if name in topics_set:
                    _render_principles_topics_only(lines, data["principles"])
                else:
                    _render_principles(lines, data["principles"])
            case "project_specific":
                entries = data.get("project_specific", [])
                if name in topics_set:
                    _render_project_specific_topics_only(lines, entries)
                else:
                    for entry in entries:
                        lines.extend(_render_project_specific(entry))
            case "branching_strategy":
                if "branching_strategy" in data:
                    _render_branching_strategy(lines, data["branching_strategy"])
            case "acceptance_surfaces":
                if "acceptance_surfaces" in data:
                    _render_acceptance_surfaces(lines, data["acceptance_surfaces"])
            case "test_layout":
                if "test_layout" in data:
                    _render_test_layout(lines, data["test_layout"])

    return "\n".join(lines)


def render_markdown(data: dict) -> str:
    """Render a system context dict as markdown (all canonical sections)."""
    return render_subset(data)


def render_section(data: dict, name: str) -> str | None:
    """Render one named section. Returns None when name is unknown.

    `name` can be a canonical section (renders via `render_subset` with
    `sections=[name]`, minus the document header) or a `project_specific`
    entry's `name` field (renders just that entry).
    """
    if name in _SECTION_HEADINGS:
        return render_subset(data, sections=[name], include_doc_header=False)

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


def _render_principles(lines: list[str], decisions: list[dict]) -> None:
    lines.append("## Principles")
    lines.append("")
    for d in decisions:
        rationale = f" — {d['rationale']}" if d.get("rationale") else ""
        lines.append(f"- **{d['topic']}:** {d['decision']}{rationale}")
    lines.append("")


def _render_principles_topics_only(lines: list[str], decisions: list[dict]) -> None:
    lines.append("## Principles (topics)")
    lines.append("")
    for d in decisions:
        lines.append(f"- {d['topic']}")
    lines.append("")


def _render_branching_strategy(lines: list[str], bs: dict) -> None:
    lines.append("## Branching Strategy")
    lines.append("")
    stage = bs.get("stage", 0)
    lines.append(f"- **Stage:** {_STAGE_NAMES.get(stage, f'Stage {stage}')}")
    if "user_namespace" in bs:
        # Marked when the use site drops it, for the same reason
        # integration_branch is (below): branch naming READS this field, so
        # rendering a value that is not in force would tell the agent branches
        # are cut under a prefix nothing actually uses.
        ns_mark = (
            ""
            if healed_user_namespace(bs) is not None
            else " — ⚠️ NOT USABLE as a branch-name segment; branch names fall"
            " back to the git identity"
        )
        lines.append(f"- **User Namespace:** {bs['user_namespace']}{ns_mark}")
    if bs.get("protected_branches"):
        branches = ", ".join(f"`{b}`" for b in bs["protected_branches"])
        lines.append(f"- **Protected Branches:** {branches}")
    if bs.get("integration_branch"):
        # Shown even when unusable — it IS what is on disk, and hiding it
        # would make the config unfixable — but marked, so the SMM never
        # claims merges target a value that branch resolution rejects. The
        # fallback named here is branch_resolution._DEFAULT_PRIMARY; it is
        # spelled out rather than imported (smm/ must not depend on
        # scripts/), and kept in sync by a pin in
        # tests/smm/test_system_context_schema_fields.py.
        value = bs["integration_branch"]
        mark = (
            ""
            if usable_git_ref_name(value)
            else " — ⚠️ NOT USABLE as a git ref; branch operations fall back to `main`"
        )
        lines.append(f"- **Integration Branch:** `{value}`{mark}")
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


def _render_test_layout(lines: list[str], layout: dict | None) -> None:
    lines.append("## Test Layout")
    lines.append("")
    if not layout:
        lines.append("(none)")
        lines.append("")
        return
    convention = layout.get("convention", "?")
    overrides = layout.get("overrides", [])
    lines.append(f"- **Convention:** {convention}")
    if overrides:
        lines.append(f"- **Overrides:** {len(overrides)} custom rule(s)")
    lines.append("")


def _render_project_specific_topics_only(lines: list[str], entries: list[dict]) -> None:
    lines.append("## Project Specific (names)")
    lines.append("")
    for entry in entries:
        lines.append(f"- {entry['name']}")
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
