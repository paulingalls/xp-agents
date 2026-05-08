#!/usr/bin/env python3
"""Render the LAST_SESSION block for the xp-kickoff preload.

Reads session_history.json and prints a `### LAST_SESSION` block with the
last 1-2 entries' summary plus open carry_forward notes/recommendations.
Event ids in `references` are NEVER rendered — humans don't read those.

Fail-quiet contract: any exception (missing file, corrupt JSON, schema
mismatch, symlink) results in exit 0 with empty stdout. The kickoff
preload must never break because of a malformed history file.
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import session_history  # noqa: E402

_RENDER_LIMIT = 2
_SECTION_HEADER = "### LAST_SESSION"


def run(smm_dir: Path) -> str:
    """Return the rendered LAST_SESSION block, or "" if nothing to render."""
    try:
        data = session_history.load_history(smm_dir)
    except (ValueError, OSError):
        return ""

    entries = data.get("entries", [])
    if not entries:
        return ""

    lines: list[str] = [_SECTION_HEADER, ""]
    for entry in entries[-_RENDER_LIMIT:]:
        summary = entry.get("summary", "")
        if summary:
            lines.append(summary)
        for item in entry.get("carry_forward", []):
            note = item.get("note", "")
            recommendation = item.get("recommendation", "")
            if note:
                lines.append(f"- {note}")
            if recommendation:
                lines.append(f"  → {recommendation}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render LAST_SESSION block from session_history.json."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    block = run(args.smm_dir)
    if block:
        print(block, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
