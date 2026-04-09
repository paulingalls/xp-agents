#!/usr/bin/env python3
"""Pure rendering of curated SMM dict to markdown.

No I/O, no file operations — takes a parsed SMM dict and returns
markdown strings. Counterpart to smm_store.py (I/O) and smm_schema.py
(validation).

Also provides extract_pillar / extract_pillars for subsetting
(used by subagent_start.py for Explore-tier injection).
"""

import sys
from pathlib import Path

from smm_schema import PILLARS

_PILLAR_TITLES = {
    "intent": "Intent",
    "constraints": "Constraints",
    "risks": "Risks",
    "wisdom": "Wisdom",
}


def _render_entry(entry: dict) -> str:
    """Render a single pillar entry as a markdown bullet."""
    return f"- {entry.get('content', '')}"


def _render_pillar_section(entries: list, pillar: str) -> str:
    """Render one pillar as a markdown section."""
    title = _PILLAR_TITLES.get(pillar, pillar.title())
    lines = [f"## {title}"]
    for entry in entries:
        lines.append(_render_entry(entry))
    return "\n".join(lines)


def _render_sprint_section(sprint: dict) -> str:
    """Render the Sprint section from sprint data."""
    sprint_id = sprint.get("sprint_id", "")
    if not sprint_id:
        return "## Sprint\n- No active sprint"

    goal = sprint.get("goal", "")
    by_status = sprint.get("stories_by_status", {})
    r = by_status.get("ready", 0)
    ip = by_status.get("in_progress", 0)
    d = by_status.get("done", 0)
    df = by_status.get("deferred", 0)

    lines = [
        "## Sprint",
        f"- {sprint_id}: {goal} "
        f"[{r + ip + d + df} stories: "
        f"{r} ready, {ip} in-progress, {d} done, {df} deferred]",
    ]

    for blocker in sprint.get("blockers", []):
        lines.append(f"- Blocker: {blocker}")

    lines.append("- Details: see sprint.md")
    return "\n".join(lines)


def render_markdown(
    smm: dict,
    *,
    sprint: dict | None = None,
) -> str:
    """Render a full curated SMM as markdown.

    Args:
        smm: Parsed SMM dict with intent/constraints/risks/wisdom pillars.
        sprint: Optional sprint data (from sprint_parser.parse_sprint_data).
            If provided, a Sprint section is prepended.

    Returns:
        Complete markdown string with header and four pillar sections.
    """
    parts = ["# Shared Mental Model", ""]

    if sprint is not None:
        parts.append(_render_sprint_section(sprint))
        parts.append("")

    for pillar in PILLARS:
        entries = smm.get(pillar, [])
        parts.append(_render_pillar_section(entries, pillar))
        parts.append("")

    return "\n".join(parts)


def extract_pillar(smm: dict, pillar: str) -> str:
    """Extract a single pillar section as markdown.

    Returns empty string if the pillar name is not recognized.
    """
    if pillar not in _PILLAR_TITLES:
        return ""
    entries = smm.get(pillar, [])
    return _render_pillar_section(entries, pillar) + "\n"


def extract_pillars(smm: dict, pillars: set[str]) -> str:
    """Extract multiple pillar sections, concatenated under a header.

    Used by subagent_start.py for Explore-tier injection (Intent +
    Constraints only).
    """
    parts = []
    for pillar in PILLARS:
        if pillar in pillars:
            parts.append(extract_pillar(smm, pillar))

    if not parts:
        return ""
    return "# Shared Mental Model\n\n" + "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI for shell preloads
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for shell preload scripts.

    Usage:
        python3 smm_view.py dump --smm-dir DIR
        python3 smm_view.py section <name> --smm-dir DIR
        python3 smm_view.py has-section <name> --smm-dir DIR
    """
    import argparse

    from smm_store import load_smm

    parser = argparse.ArgumentParser(description="SMM view CLI")
    sub = parser.add_subparsers(dest="command")

    dump_p = sub.add_parser("dump")
    dump_p.add_argument("--smm-dir", type=Path, required=True)

    sec_p = sub.add_parser("section")
    sec_p.add_argument("name")
    sec_p.add_argument("--smm-dir", type=Path, required=True)

    has_p = sub.add_parser("has-section")
    has_p.add_argument("name")
    has_p.add_argument("--smm-dir", type=Path, required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    smm = load_smm(args.smm_dir)

    match args.command:
        case "dump":
            print(render_markdown(smm))
        case "section":
            print(extract_pillar(smm, args.name.lower()))
        case "has-section":
            name = args.name.lower()
            entries = smm.get(name, [])
            sys.exit(0 if entries else 1)


if __name__ == "__main__":
    main()
