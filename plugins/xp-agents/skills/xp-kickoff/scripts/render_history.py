#!/usr/bin/env python3
"""Render the LAST_SESSION block for the xp-kickoff preload.

Reads session_history.json and prints `### LAST_SESSION` with the last
1-2 entries' summary plus open carry_forward notes/recommendations.
Event ids in `references` are NEVER rendered — humans don't read those.

Fail-quiet: load_history errors → return ""; missing file → empty history.
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import session_history  # noqa: E402

_RENDER_LIMIT = 2


def run(smm_dir: Path) -> str:
    """Return the rendered LAST_SESSION block, or "" if nothing to render."""
    try:
        data = session_history.load_history(smm_dir)
    except (ValueError, OSError):
        return ""

    entries = data.get("entries", [])
    if not entries:
        return ""

    lines: list[str] = ["### LAST_SESSION", ""]
    for entry in entries[-_RENDER_LIMIT:]:
        if summary := entry.get("summary", ""):
            lines.append(summary)
        for item in entry.get("carry_forward", []):
            if note := item.get("note", ""):
                lines.append(f"- {note}")
            if rec := item.get("recommendation", ""):
                lines.append(f"  → {rec}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render LAST_SESSION block from session_history.json."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    if block := run(args.smm_dir):
        print(block, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
