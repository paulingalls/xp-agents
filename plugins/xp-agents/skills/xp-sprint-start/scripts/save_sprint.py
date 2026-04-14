#!/usr/bin/env python3
"""Save sprint: write sprint.json atomically + handle acceptance flow.

Called by xp-sprint-start, xp-work-selection, and xp-accept to persist
sprint.json. After writing, it:

- Clears the .needs-sprint marker if sprint now has active stories.
- If the .accept marker was present and no in-progress stories remain,
  treats this as acceptance completion: clears .accept, records an
  iteration_complete status event, and — if the sprint is now complete —
  prints a sprint-review nudge to stdout for the main agent to see.

Usage:
    echo '<json>' | python3 save_sprint.py --smm-dir DIR
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import marker_names  # noqa: E402
import sprint_store  # noqa: E402
from event_schema import (  # noqa: E402
    EVENT_TYPE_STATUS,
    STATUS_ACTION_ITERATION_COMPLETE,
)

_SPRINT_REVIEW_NUDGE = (
    "\n**Sprint complete!** All stories are done or deferred. "
    "Run `/xp-sprint-review` to review the sprint."
)


def run(data: dict, smm_dir: Path) -> None:
    """Write sprint.json and run the acceptance-flow side effects.

    Args:
        data: Sprint data dict (validated by sprint_store).
        smm_dir: SMM directory path.
    """
    accept_marker = smm_dir / marker_names.ACCEPT
    accept_marker_existed = accept_marker.exists()

    sprint_store.save_sprint(smm_dir, data)

    # Acceptance flow: .accept was present, no in-progress stories.
    # Use in-memory data to avoid re-reading the file we just wrote.
    has_ip = any(s["status"] == "in-progress" for s in data["stories"])
    if accept_marker_existed and not has_ip:
        accept_marker.unlink(missing_ok=True)

        event = _common.make_event(
            EVENT_TYPE_STATUS,
            "save-sprint",
            "Iteration complete — accept verification done.",
            working_on=[],
            metadata={"action": STATUS_ACTION_ITERATION_COMPLETE},
        )
        _common.append_safe(smm_dir, event)

        is_done = not sprint_store.has_active_stories_data(data)
        if is_done:
            print(_SPRINT_REVIEW_NUDGE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save sprint.json atomically")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    args = parser.parse_args()

    raw = sys.stdin.read()
    data = json.loads(raw)
    run(data, args.smm_dir)


if __name__ == "__main__":
    main()
