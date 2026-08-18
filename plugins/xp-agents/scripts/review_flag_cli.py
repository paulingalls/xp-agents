#!/usr/bin/env python3
"""Set a review-cycle flag (and emit its lifecycle event) from close-skill prose.

Step 4b of the shared close pipeline runs /code-review via the Workflow tool
(async). A Workflow completion does NOT fire review_cycle_done.py (a
PostToolUse:Skill|Agent hook), so neither the marker flag nor the lifecycle
event that hook produces gets set on its own. The close skill calls this CLI
at LAUNCH so:

  - close_cycle_stop_gate defers during the async review window
    (review_records.review_mid_cycle True), and
  - the xp-quality-review preload emits MODE=consume-findings for the findings.

It calls it again with `--complete` once the findings are in hand, so
retro_metrics still counts the close-time review — the CLI emits the same
STATUS_ACTION_*_COMPLETE event review_cycle_done would (retro_metrics counts it
via _ACTION_TO_COUNTER; without it the close's broad review is invisible).

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

THREE ACTIONS, and the split between them is what keeps the count honest:

  - the ARM (no flag needed, no option) sets the marker and emits NOTHING. It
    runs at LAUNCH, where nothing has completed yet.
  - `--complete` emits the lifecycle event and leaves the marker set. It runs
    when the findings are in hand, which is when a review has actually
    completed. The marker stays because /xp-quality-review has yet to consume
    those findings; the cycle ends where it always did, at the reviewer's
    SubagentStop.
  - `--disarm` clears the marker and emits nothing. Step 4b invokes it for a
    launch that failed AND for a run that completed having reviewed nothing —
    an errored result or an empty scope, which a caller watching only the
    launch would read as success. A close abandoned outright still has no
    invoker; the flag survives to the next session there, and the abandonment
    recorder is where that would be wired. Without the disarm the flag would
    survive every one of these, since only a landed commit clears the cycle —
    and the next /xp-quality-review
    would read consume-findings, ask for findings nobody produced, and skip the
    self-find branch that would have found the bugs itself.

The arm used to emit at launch, which said a review had completed the moment
one started. The broad review found the consequence on its own branch: on the
documented FALLBACK path the count was wrong every time, because the by-hand
arm emitted one event, the disarm emits none by design, and the fallback
Skill's own PostToolUse then emitted a second for the same review.
retro_metrics counts occurrences with no dedup. Splitting the emission out
closes that, and the debt recorded for it: exactly one event on either path —
this CLI's on the primary, the hook's on the fallback.
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


_DEFAULT_FLAG = "simplify_done"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smm-dir", required=True)
    parser.add_argument("--cwd", default=".")
    # MUTUALLY EXCLUSIVE, because the two describe opposite outcomes of the
    # same review and there is no sensible reading of both. Given both,
    # `--complete` used to win silently: the flag was left alone and a
    # completion event was emitted for the review the caller was trying to
    # withdraw, which is the exact miscount the arm/emit split exists to stop.
    outcome = parser.add_mutually_exclusive_group()
    outcome.add_argument(
        "--disarm",
        action="store_true",
        help=(
            "clear the flag instead of setting it, and emit no lifecycle event "
            "— for a launch that errored or a review abandoned part-way"
        ),
    )
    outcome.add_argument(
        "--complete",
        action="store_true",
        help=(
            "record that the review finished: emit its lifecycle event and "
            "leave the flag set for the quality review to consume"
        ),
    )
    # OPTIONAL, and defaulted, so the shipped close prose can invoke this
    # without spelling an internal state field. Naming one in instructions that
    # ship to every project is what the prose vocabulary pins exist to
    # discourage; the table has exactly one member, so there is nothing for a
    # caller to choose between. An explicit flag is still accepted.
    parser.add_argument(
        "flag",
        nargs="?",
        default=_DEFAULT_FLAG,
        choices=sorted(_FLAG_LIFECYCLE),
        help="the review-cycle flag to set (defaults to the only one)",
    )
    args = parser.parse_args(argv)

    smm_dir = Path(args.smm_dir)
    agent_id = identity.review_flags_key(args.cwd)

    if not args.complete:
        # Clearing ONE flag, never the whole record: quality_review_done is the
        # per-increment commit gate's flag, and this CLI is prose-invoked.
        # clear_review_flags here would let anything able to run a command
        # re-open a gate a real review had closed.
        review_records.set_review_flag(
            smm_dir, agent_id, args.flag, value=not args.disarm
        )
        return

    action, content = _FLAG_LIFECYCLE[args.flag]
    event = _common.make_event(
        _common.STATUS, agent_id, content, working_on=[], metadata={"action": action}
    )
    _common.append_safe(smm_dir, event)


if __name__ == "__main__":
    main()
