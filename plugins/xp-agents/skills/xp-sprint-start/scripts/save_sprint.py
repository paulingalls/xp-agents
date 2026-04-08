#!/usr/bin/env python3
"""Save sprint: write sprint.md atomically + handle acceptance flow.

Called by xp-sprint-start, xp-work-selection, and xp-accept to persist
sprint.md. After writing, it:

- Clears the .needs-sprint marker if sprint now has active stories.
- If the .accept marker was present and no in-progress stories remain,
  treats this as acceptance completion: clears .accept, records an
  iteration_complete status event, and — if the sprint is now complete —
  prints a sprint-review nudge to stdout for the main agent to see.

The .accept marker is set by pre_tool_write when code is written during
an in-progress sprint, so its presence is a reliable signal that the
current write is part of an acceptance flow (not initial creation or
story selection). This lets one script serve all three callers without
context-specific branching.

Usage:
    echo '<markdown>' | python3 save_sprint.py --smm-dir DIR
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import marker_names  # noqa: E402
import sprint_state  # noqa: E402
from _append_impl import write_text_atomic  # noqa: E402
from event_schema import (  # noqa: E402
    EVENT_TYPE_STATUS,
    STATUS_ACTION_ITERATION_COMPLETE,
)

_SPRINT_REVIEW_NUDGE = (
    "\n**Sprint complete!** All stories are done or deferred. "
    "Run `/xp-sprint-review` to review the sprint."
)


def run(content: str, smm_dir: Path) -> None:
    """Write sprint.md and run the acceptance-flow side effects.

    Args:
        content: Markdown content to write.
        smm_dir: SMM directory path.
    """
    target = smm_dir / "sprint.md"

    if target.is_symlink():
        raise OSError(f"sprint.md is a symlink: {target}")

    accept_marker = smm_dir / marker_names.ACCEPT
    accept_marker_existed = accept_marker.exists()

    write_text_atomic(target, content)

    # Clear NEEDS_SPRINT when the sprint now has active stories
    if sprint_state.has_active_stories(content):
        (smm_dir / marker_names.NEEDS_SPRINT).unlink(missing_ok=True)

    # Acceptance flow: .accept was present, no in-progress stories remain
    if accept_marker_existed and not sprint_state.has_in_progress_stories(content):
        accept_marker.unlink(missing_ok=True)

        event = _common.make_event(
            EVENT_TYPE_STATUS,
            "save-sprint",
            "Iteration complete — accept verification done.",
            working_on=[],
            metadata={"action": STATUS_ACTION_ITERATION_COMPLETE},
        )
        _common.append_safe(smm_dir, event)

        if sprint_state.is_sprint_complete(content):
            print(_SPRINT_REVIEW_NUDGE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save sprint.md atomically")
    parser.add_argument(
        "--smm-dir",
        type=Path,
        required=True,
        help="SMM directory path",
    )
    args = parser.parse_args()

    content = sys.stdin.read()
    run(content, args.smm_dir)


if __name__ == "__main__":
    main()
