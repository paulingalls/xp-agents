#!/usr/bin/env python3
"""Surface acceptance_execution type per in-progress story.

Called by xp-accept preload to show each story's runner type so the
skill can route between automated execution and manual walkthrough.

Usage:
    python3 acceptance_types.py --sprint-file /path/to/sprint.json
"""

import argparse
import json
import sys
from pathlib import Path


def format_acceptance_types(sprint: dict) -> str:
    """Format acceptance types for in-progress stories.

    Returns empty string if no in-progress stories exist.
    """
    in_progress = [
        s for s in sprint.get("stories", []) if s.get("status") == "in-progress"
    ]
    if not in_progress:
        return ""

    lines = ["### Acceptance Types"]
    for story in in_progress:
        ae = story.get("acceptance_execution")
        ae_type = ae["type"] if ae else "manual"
        lines.append(f"{story['id']}: {ae_type}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surface acceptance_execution types for in-progress stories"
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
