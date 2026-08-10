#!/usr/bin/env python3
"""Set a review-cycle flag (and emit its lifecycle event) from close-skill prose.

Step 4b of the shared close pipeline runs /code-review via the Workflow tool
(async). A Workflow completion does NOT fire review_cycle_done.py (a
PostToolUse:Skill|Agent hook), so neither the marker flag nor the lifecycle
event that hook produces gets set on its own. The close skill calls this CLI
when it LAUNCHES the workflow so:

  - close_cycle_stop_gate defers during the async review window
    (markers.review_mid_cycle True),
  - the xp-quality-review preload emits MODE=consume-findings for the findings,
    and
  - retro_metrics still counts the close-time review — the CLI emits the same
    STATUS_ACTION_*_COMPLETE event review_cycle_done would (retro_metrics counts
    it via _ACTION_TO_COUNTER; without it the close /code-review is invisible).

The flag is keyed on the cwd-resolved agent_id via
identity.resolve_agent_id_from_cwd. The xp-quality-review preload
(skills/xp-quality-review/scripts/review_mode.py) reads it the same way;
close_cycle_stop_gate reads it via resolve_agent_id(input_data), which falls
back to that same cwd resolution only when agent_id is empty. In every close
mode that runs Step 4b — sprint/plan/free-close — there is no closing-story
worktree, so ${TEAMMATE_CWD:-.} resolves to the orchestrator ('main'),
matching the reader; story-close (the only closing-worktree case) skips
Step 4b entirely.

This CLI is the async-Step-4b substitute for review_cycle_done's simplify leg,
so the two must emit the same action and content; pinned in
test_review_flag_cli.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import _common
import event_schema
import identity
import markers

# The flags this CLI can set, each paired with the lifecycle event
# review_cycle_done emits for the equivalent completed review. Keys double as
# the argparse `choices` (the valid review-cycle flags this CLI sets). Only
# simplify_done is needed: it is the sole leg the async-Workflow Step 4b must
# substitute for. /xp-quality-review still launches via the Skill tool, so
# review_cycle_done sets quality_review_done itself — no CLI leg for it.
_FLAG_LIFECYCLE: dict[str, tuple[str, str]] = {
    "simplify_done": (
        event_schema.STATUS_ACTION_SIMPLIFY_COMPLETE,
        "Code review complete",
    ),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", default=".")
    parser.add_argument(
        "flag",
        choices=sorted(_FLAG_LIFECYCLE),
        help="the review-cycle flag to set (e.g. simplify_done)",
    )
    args = parser.parse_args(argv)

    smm_dir = Path(args.smm_dir)
    agent_id = identity.resolve_agent_id_from_cwd(args.cwd)
    markers.set_review_flag(smm_dir, agent_id, args.flag)

    action, content = _FLAG_LIFECYCLE[args.flag]
    event = _common.make_event(
        _common.STATUS, agent_id, content, working_on=[], metadata={"action": action}
    )
    _common.append_safe(smm_dir, event)


if __name__ == "__main__":
    main()
