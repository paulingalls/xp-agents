#!/usr/bin/env python3
"""CLI for SMM operations.

Thin wrapper over smm_store.py for shell scripts and skills.
Python scripts may import the rendering functions directly.

Also provides extract_pillar / extract_pillars for subsetting
(used by subagent_start.py for Explore-tier injection).
"""

import argparse
import sys
from pathlib import Path

import smm_store
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


def render_markdown(smm: dict) -> str:
    """Render a full curated SMM as markdown.

    Args:
        smm: Parsed SMM dict with intent/constraints/risks/wisdom pillars.

    Returns:
        Complete markdown string with header and four pillar sections.
    """
    parts = ["# Shared Mental Model", ""]

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
# CLI commands
# ---------------------------------------------------------------------------


def _cmd_dump(args: argparse.Namespace) -> int:
    smm = smm_store.load_smm(args.smm_dir)
    print(render_markdown(smm))
    return 0


def _cmd_section(args: argparse.Namespace) -> int:
    smm = smm_store.load_smm(args.smm_dir)
    print(extract_pillar(smm, args.name.lower()))
    return 0


def _cmd_has_section(args: argparse.Namespace) -> int:
    smm = smm_store.load_smm(args.smm_dir)
    name = args.name.lower()
    entries = smm.get(name, [])
    return 0 if entries else 1


def _cmd_save(args: argparse.Namespace) -> int:
    import json

    content = sys.stdin.read()
    try:
        save(content, smm_dir=args.smm_dir)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Library function for save (callable from Python or CLI)
# ---------------------------------------------------------------------------


def save(content: str, *, smm_dir: Path) -> None:
    """Parse JSON, validate, write, update watermark, compact.

    Raises:
        json.JSONDecodeError: If content is not valid JSON.
        ValueError: If content fails SMM schema validation.
    """
    import contextlib
    import json

    import compact
    import materialize

    data = json.loads(content)
    smm_store.save_smm(smm_dir, data)

    events, _ = materialize.parse_events(smm_dir)
    materialize.write_curation_watermark(smm_dir, len(events), "xp-housekeeping")

    with contextlib.suppress(OSError, ValueError):
        compact.compact_after_curation(smm_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="SMM CLI")
    parser.add_argument(
        "--smm-dir", type=Path, required=True, help="SMM directory path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("dump", help="Render full SMM as markdown")

    sec_p = sub.add_parser("section", help="Render a single pillar")
    sec_p.add_argument("name", help="Pillar name (intent/constraints/risks/wisdom)")

    has_p = sub.add_parser("has-section", help="Check if a pillar has entries")
    has_p.add_argument("name", help="Pillar name (intent/constraints/risks/wisdom)")

    sub.add_parser("save", help="Save SMM from stdin JSON")

    args = parser.parse_args()

    dispatch = {
        "dump": _cmd_dump,
        "section": _cmd_section,
        "has-section": _cmd_has_section,
        "save": _cmd_save,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
