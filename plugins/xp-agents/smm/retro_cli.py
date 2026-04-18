#!/usr/bin/env python3
"""Render retrospective JSON as markdown + drop echo-enforcement marker.

Reads a retrospective JSON file (as written by scripts/save_retrospective.py),
emits a Keep/Fix/Try markdown report on stdout, and atomically writes
.pending-render-retro-{agent_id} at the SMM root via markers.marker_write
(symlink-safe, per-agent isolated). The marker carries the signature header
so the echo-gate hook can confirm the assistant echoed the render to the
user verbatim.

Usage:
    retro_cli.py --smm-dir DIR render <retro-json-path> [--agent-id ID]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import marker_names
import markers
from identity import resolve_agent_id_from_cwd

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
    agent_id = args.agent_id or resolve_agent_id_from_cwd(os.getcwd())
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error rendering {args.path}: {exc}", file=sys.stderr)
        return 1
    markdown = render_markdown(data)
    try:
        markers.marker_write(
            args.smm_dir,
            markers.PENDING_RENDER_RETRO,
            SIGNATURE + "\n",
            agent_id,
        )
    except ValueError as exc:
        print(f"Error writing render marker: {exc}", file=sys.stderr)
        return 1
    print(markdown)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrospective render CLI")
    parser.add_argument(
        "--smm-dir", type=Path, required=True, help="SMM directory path"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render_p = sub.add_parser("render", help="Render retrospective JSON as markdown")
    render_p.add_argument("path", type=Path, help="Path to retrospective JSON file")
    render_p.add_argument(
        "--agent-id",
        default=None,
        help="Agent ID for marker scoping (default: derived from CWD)",
    )

    args = parser.parse_args()
    dispatch = {"render": _cmd_render}
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
