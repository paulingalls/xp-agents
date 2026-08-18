#!/usr/bin/env python3
"""Set a review-cycle flag (and emit its lifecycle event) from close-skill prose.

Step 4b of the shared close pipeline runs /code-review via the Workflow tool
(async). A Workflow completion does NOT fire review_cycle_done.py (a
PostToolUse:Skill|Agent hook), so neither the marker flag nor the lifecycle
event that hook produces gets set on its own. The close skill calls this CLI
when it LAUNCHES the workflow so:

  - close_cycle_stop_gate defers during the async review window
    (review_records.review_mid_cycle True),
  - the xp-quality-review preload emits MODE=consume-findings for the findings,
    and
  - retro_metrics still counts the close-time review — the CLI emits the same
    STATUS_ACTION_*_COMPLETE event review_cycle_done would (retro_metrics counts
    it via _ACTION_TO_COUNTER; without it the close /code-review is invisible).

The flag is keyed via identity.review_flags_key, which every other writer,
reader and clear of the flags also calls — that function documents why the key
is the reviewing SESSION's checkout and not the payload's agent_id, and
test_review_flag_cli.py pins this CLI's write against close_cycle_stop_gate's
read.

In every close mode that runs Step 4b — sprint/plan/free-close — there is no
closing-story worktree, so ${TEAMMATE_CWD:-.} resolves to the orchestrator
('main'); story-close (the only closing-worktree case) skips Step 4b entirely.

This CLI is the async-Step-4b substitute for review_cycle_done's simplify leg,
so the two must emit the same action and content; pinned in
test_review_flag_cli.py.

`--disarm` withdraws the arm. It exists because the arm happens at LAUNCH and
the only thing that clears the cycle is a landed commit (`end_review_cycle`,
off the reviewer's SubagentStop) — so a launch that errors, or a review
abandoned part-way, leaves the flag set for good. The next
/xp-quality-review then reads consume-findings and asks for findings nobody
produced, while the self-find branch that would have found the bugs itself
never runs. The withdrawal emits NO lifecycle event: retro_metrics counts
occurrences, so reusing the arm's entry would report two close-time reviews
where one was launched and none finished.

Accepted residual, recorded as debt: the arm's SIMPLIFY_COMPLETE was already
emitted, so a disarmed cycle still reads to retro_metrics as one completed
review. Splitting the arm from the emission (arm at launch, emit when findings
return) is the fix, and it needs the launcher to call this CLI twice.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import _common
import event_schema
import identity
import review_records

# The flags this CLI can set, each paired with the lifecycle event
# review_cycle_done emits for the equivalent completed review. Keys double as
# the argparse `choices` (the valid review-cycle flags this CLI sets). Only
# simplify_done is needed: it is the sole leg the async-Workflow Step 4b must
# substitute for.
#
# quality_review_done has NO leg here, deliberately. It is the flag the commit
# gate reads, and this CLI is prose-invoked — a leg for it would make the gate
# clearable by anything that can run a command, without a review having
# happened, which is the hole v5.16.0/v5.17.0 exist to close. Its one writer is
# `review_cycle_legs`, off the xp-code-reviewer's SubagentStop, the only signal
# in the family that fires at completion. The cost is accepted and real: a
# reviewer that never reaches SubagentStop leaves the gate armed with nothing
# able to clear it, and the recovery is another review, not a manual override.
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
        "--disarm",
        action="store_true",
        help=(
            "clear the flag instead of setting it, and emit no lifecycle event "
            "— for a launch that errored or a review abandoned part-way"
        ),
    )
    parser.add_argument(
        "flag",
        choices=sorted(_FLAG_LIFECYCLE),
        help="the review-cycle flag to set (e.g. simplify_done)",
    )
    args = parser.parse_args(argv)

    smm_dir = Path(args.smm_dir)
    agent_id = identity.review_flags_key(args.cwd)
    review_records.set_review_flag(smm_dir, agent_id, args.flag, value=not args.disarm)
    if args.disarm:
        # Clearing ONE flag, never the whole record: quality_review_done is the
        # per-increment commit gate's flag, and this CLI is prose-invoked.
        # clear_review_flags here would let anything able to run a command
        # re-open a gate a real review had closed.
        return

    action, content = _FLAG_LIFECYCLE[args.flag]
    event = _common.make_event(
        _common.STATUS, agent_id, content, working_on=[], metadata={"action": action}
    )
    _common.append_safe(smm_dir, event)


if __name__ == "__main__":
    main()
