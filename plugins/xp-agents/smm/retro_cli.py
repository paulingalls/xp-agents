#!/usr/bin/env python3
"""Render the latest retrospective as Keep/Fix/Try markdown.

Reads the latest retrospective JSON from <smm-dir>/retrospectives/
(written by scripts/save_retrospective.py) and emits a Keep/Fix/Try
markdown report on stdout. The CLI encapsulates storage layout —
callers don't need to know where retros live or which is latest.

Usage:
    retro_cli.py --smm-dir DIR render
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


def _find_latest_retro(smm_dir: Path) -> Path | None:
    """Return the lexicographically largest retrospective JSON, or None.

    File names are ISO-8601 timestamps so lexicographic max == newest.
    """
    retros_dir = smm_dir / marker_names.RETROSPECTIVES_DIR
    if not retros_dir.is_dir():
        return None
    candidates = sorted(retros_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def _cmd_render(args: argparse.Namespace) -> int:
    retros_dir = args.smm_dir / marker_names.RETROSPECTIVES_DIR
    latest = _find_latest_retro(args.smm_dir)
    if latest is None:
        print(f"No retrospectives found under {retros_dir}/", file=sys.stderr)
        return 1
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error rendering {latest}: {exc}", file=sys.stderr)
        return 1
    print(render_markdown(data))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retrospective render CLI",
        epilog="Examples:\n  retro_cli.py --smm-dir DIR render",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory (retrospectives are read from <smm-dir>/retrospectives/)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render", help="Render the latest retrospective as markdown")

    args = parser.parse_args()
    dispatch = {"render": _cmd_render}
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
