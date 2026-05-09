#!/usr/bin/env python3
"""Surface acceptance_execution type per in-motion story.

Called by xp-accept preload to show each story's runner type so the
skill can route between automated execution and manual walkthrough.

Usage:
    python3 acceptance_types.py --sprint-file /path/to/sprint.json
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

from sprint_status import select_in_motion_stories  # noqa: E402


def format_acceptance_types(sprint: dict) -> str:
    """Format acceptance types for in-motion stories.

    Shares select_in_motion_stories with concern_triage so both preload
    helpers stay in lockstep on the dispatch contract.
    """
    in_motion = select_in_motion_stories(sprint.get("stories", []))
    if not in_motion:
        return ""

    lines = ["### Acceptance Types"]
    for story in in_motion:
        ae = story.get("acceptance_execution")
        ae_type = ae["type"] if ae else "manual"
        lines.append(f"{story['id']}: {ae_type}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surface acceptance_execution types for in-motion stories"
    )
    parser.add_argument(
        "--sprint-file",
        type=Path,
        required=True,
        help="Path to sprint.json",
    )
    args = parser.parse_args()

    try:
        sprint = json.loads(args.sprint_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Error reading sprint file: {exc}", file=sys.stderr)
        sys.exit(1)

    output = format_acceptance_types(sprint)
    if output:
        print(output)


if __name__ == "__main__":
    main()
