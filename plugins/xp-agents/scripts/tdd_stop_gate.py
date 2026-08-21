#!/usr/bin/env python3
"""Stop command hook: TDD gate.

Blocks stop when the most recent test run in the event log failed.
Replaces the tdd_check.md prompt hook with deterministic event parsing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import identity
import tdd_check

_WATERMARK_ID = "tdd-stop-gate"


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block reason if tests failing, None otherwise.

    **This function asks "who am I?" once, and the answer comes from one
    source.** It has three identity-shaped decisions — whose test signals count
    (`find_last_test_signal`), whether this reader may release on a sibling
    (by AUTHORSHIP), and which coordination key to compare against
    (`resolve_agent_id`) — and every one of them derives from the hook payload's
    `cwd` plus the in-place marker, never from the raw `agent_id` field. That
    field is present only when a hook fires inside a subagent call; Stop fires on
    the main thread, so reading it directly yielded `""` on every firing and
    disarmed the gate entirely. A second spelling of any of these three is how
    the fail-open comes back.
    """
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if not events:
        return None

    # Bound once and shared with every reader below. Two independently-written
    # spellings of the reader's cwd is the same defect shape as the agent-id
    # disagreement this gate was fixed for.
    cwd = input_data.get("cwd", ".")

    signal, author = tdd_check.find_last_test_signal_with_author(events, cwd, smm_dir)
    if signal == "fail":
        # RESOLVED, never the raw payload field. The harness sends `agent_id`
        # only when a hook fires inside a subagent call, and Stop fires on the
        # main thread — so the raw read was always `""`, nothing in
        # coordination equals `""`, and `has_active_teammates` answered yes
        # against every entry. `post_tool_use` writes one on every file write
        # with a 30-minute TTL, so this gate released unconditionally.
        #
        # `resolve_agent_id` specifically, not a richer resolution: it is the
        # same function `post_tool_use` uses to WRITE the coordination key
        # being compared against, and a reader that does not share the writer's
        # key space cannot answer this question at all.
        #
        # The release is the LEAD's alone. `find_last_test_signal` has already
        # scoped this read — a teammate saw only its own signals — so a teammate
        # reaching here is looking at a failure that is provably its own, and
        # "a teammate may own it" is false by construction. Same source as the
        # scoping above, so the two cannot disagree; paid only on this branch,
        # where we would otherwise block.
        #
        # NARROWED to authorship. `_is_another_trees_agent` already dropped every
        # story-worktree signal above, so the failures still arriving here are
        # the ones it cannot place: an opaque subagent id, or a worktree whose
        # name is not `worktree-story-*`. Releasing on "some sibling is active"
        # therefore released the reader's OWN red — authored with its own id —
        # whenever any sibling held a coordination entry. A fail-open, and the
        # release's stated basis ("only the lead reads unscoped") had already
        # been falsified by that filter.
        #
        # `resolve_agent_id` is the same function that WRITES the coordination
        # key being read, which is the one-identity-source argument above.
        #
        # NO "only the lead may release" guard any more, and none is needed: a
        # worktree teammate's own failures are the only ones it can see, and its
        # author and its resolved id both come off the same cwd — so authorship
        # refuses the release for it without a second question being asked. That
        # guard was `reader_scope_owner`, now deleted; it asserted a rule the
        # in-place change falsified.
        #
        # RESIDUAL, unclosable on this signal: the reader's own subagent authors
        # an opaque id too, indistinguishable from a worktree teammate's. Events
        # carry no session id, so the author is the best discriminator available;
        # this still releases a red that is really ours.
        agent_id = identity.resolve_agent_id(input_data)
        if author != agent_id and coordination.has_active_teammates(smm_dir, agent_id):
            return None  # A sibling may own the failing tests
        return "Tests are failing. Fix failing tests before stopping."

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Test failures detected — fix before stopping.")
    sys.exit(0)
