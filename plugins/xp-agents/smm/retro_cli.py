#!/usr/bin/env python3
"""Render retrospective JSON as Keep/Fix/Try markdown.

Reads a retrospective JSON file (as written by scripts/save_retrospective.py)
and emits a Keep/Fix/Try markdown report on stdout.

Usage:
    retro_cli.py --smm-dir DIR render <retro-json-path>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import marker_names

SIGNATURE = marker_names.RENDER_RETRO_SIGNATURE

_SECTIONS = (("keep", "Keep"), ("fix", "Fix"), ("try", "Try"))


def _render_section(title: str, entries: list) -> str:
    lines = [f"## {title}"]
    for entry in entries:
        content = entry.get("content", "") if isinstance(entry, dict) else str(entry)
        lines.append(f"- {content}")
    return "\n".join(lines)


def render_markdown(retro: dict) -> str:
    parts = [SIGNATURE, ""]
    for key, title in _SECTIONS:
        parts.append(_render_section(title, retro.get(key, []) or []))
        parts.append("")
    return "\n".join(parts)


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error rendering {args.path}: {exc}", file=sys.stderr)
        return 1
    print(render_markdown(data))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retrospective render CLI",
        epilog=("Examples:\n  retro_cli.py --smm-dir DIR render path/to/retro.json"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        default=None,
        help="SMM directory path (accepted for caller symmetry; not read)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render_p = sub.add_parser("render", help="Render retrospective JSON as markdown")
    render_p.add_argument("path", type=Path, help="Path to retrospective JSON file")

    args = parser.parse_args()
    dispatch = {"render": _cmd_render}
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
