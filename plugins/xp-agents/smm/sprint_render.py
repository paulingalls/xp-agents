#!/usr/bin/env python3
"""Markdown rendering for sprint dicts.

Split from sprint_store.py at the commit that pushed it over the 500-line
cap. Pure formatting — no I/O, no validation. Reads sprint dicts the
store has already loaded; emits markdown for skills, retros, and CLI.
"""

from typing import Any

from _acceptance_execution import render_acceptance_execution


def render_markdown(sprint: dict) -> str:
    """Render a sprint dict as markdown for display."""
    lines: list[str] = []

    lines.append(f"# Sprint: {sprint['goal']}")
    lines.append("")
    lines.append(f"- **Sprint ID:** {sprint['sprint_id']}")
    lines.append(f"- **Started:** {sprint['started']}")
    if sprint.get("milestone"):
        lines.append(f"- **Milestone:** {sprint['milestone']}")
    lines.append("")

    lines.append("## System Context")
    lines.append("")
    lines.append("See: system_context.json")
    lines.append("")

    lines.append("## Stories")
    lines.append("")

    for s in sprint["stories"]:
        _render_story(lines, s)

    return "\n".join(lines)


def render_story_sections(sprint: dict, story_ids: list[str]) -> str:
    """Render specific story sections as markdown."""
    if not story_ids:
        return ""
    wanted = set(story_ids)
    parts: list[str] = []
    for s in sprint["stories"]:
        if s["id"] in wanted:
            story_lines: list[str] = []
            _render_story(story_lines, s)
            parts.append("\n".join(story_lines))
    return "\n\n".join(parts)


def _render_story(lines: list[str], s: dict[str, Any]) -> None:
    """Render a single story to the lines list."""
    lines.append(f"### {s['id']}: {s['title']}")
    lines.append(f"- **Status:** {s['status']}")

    deps = ", ".join(s.get("dependencies", [])) or "none"
    lines.append(f"- **Dependencies:** {deps}")

    if s.get("milestone_ref"):
        lines.append(f"- **Milestone:** {s['milestone_ref']}")
    if s.get("design_sources"):
        lines.append(f"- **Design Sources:** {s['design_sources']}")

    if s.get("context"):
        lines.append("")
        lines.append("**Context:**")
        lines.append(s["context"])

    if s.get("file_domain"):
        lines.append("")
        lines.append("**File Domain:**")
        for fd in s["file_domain"]:
            lines.append(f"- {fd}")

    if s.get("interface_contracts"):
        lines.append("")
        lines.append("**Interface Contracts:**")
        for ic in s["interface_contracts"]:
            lines.append(f"- {ic}")

    if s.get("acceptance_criteria"):
        lines.append("")
        lines.append("**Acceptance Criteria:**")
        for ac in s["acceptance_criteria"]:
            lines.append(f"- {ac}")

    ae = s.get("acceptance_execution")
    if ae:
        lines.append("")
        render_acceptance_execution(ae, lines)

    lines.append("")
