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
identity.resolve_agent_id_from_cwd — the SAME resolution the readers
(review_mode.py, close_cycle_stop_gate.py) use. In every close mode that runs
Step 4b — sprint/plan/free-close — there is no closing-story worktree, so
${TEAMMATE_CWD:-.} resolves to the orchestrator ('main'), matching the reader;
story-close (the only closing-worktree case) skips Step 4b entirely.

Keep _FLAG_LIFECYCLE in sync with review_cycle_done._TARGET_LIFECYCLE /
_TARGET_FLAG — this CLI is the async-Step-4b substitute for that hook's
simplify/quality-review legs.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
import event_schema
import identity
import markers

# The flags this CLI can set, each paired with the lifecycle event
# review_cycle_done emits for the equivalent completed review. Keys double as
# the argparse `choices` (the valid review-cycle flags this CLI sets).
_FLAG_LIFECYCLE: dict[str, tuple[str, str]] = {
    "simplify_done": (
        event_schema.STATUS_ACTION_SIMPLIFY_COMPLETE,
        "Code review complete",
    ),
    "quality_review_done": (
        event_schema.STATUS_ACTION_QR_COMPLETE,
        "Quality review complete",
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
