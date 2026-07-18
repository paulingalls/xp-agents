#!/usr/bin/env python3
"""Surface acceptance_execution type per in-motion story.

Called by xp-accept preload to show each story's declared runner type as
an at-a-glance reference. This is informational only: Step 1 routes on
command PRESENCE, not `type` (a `type: manual` block carrying a command
takes the automated path — see the SKILL and _acceptance_execution.py).

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
    """Format each in-motion story's acceptance ROUTING for quick reference.

    Shows `<type> (automated)` when a command is present and `(walkthrough)`
    when it is absent — the same command-presence signal Step 1 routes on —
    rather than the bare `type`, which reads as walkthrough even for a
    command-bearing manual block. Informational only; routing is presence-based.

    Shares select_in_motion_stories with concern_triage so both preload
    helpers stay in lockstep on the dispatch contract.
    """
    in_motion = select_in_motion_stories(sprint.get("stories", []))
    if not in_motion:
        return ""

    lines = ["### Acceptance Types"]
    for story in in_motion:
        ae = story.get("acceptance_execution")
        # Display the ROUTING, not the bare type: Step 1 routes on command
        # PRESENCE (a manual-typed block carrying a command runs the automated
        # path), so a command present -> automated, absent -> walkthrough.
        if ae and (ae.get("command") or ae.get("commands")):
            display = f"{ae['type']} (automated)"
        elif ae:
            display = f"{ae['type']} (walkthrough)"
        else:
            display = "manual (walkthrough)"
        lines.append(f"{story['id']}: {display}")
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
