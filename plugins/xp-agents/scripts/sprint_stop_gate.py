#!/usr/bin/env python3
"""Stop command hook: unified sprint lifecycle gate.

Replaces accept_gate.py. Handles the sprint cascade (accept → review):
  1. reviewing/closing stories, or in-progress + ACCEPT marker + work
     → block "run /xp-accept" — a one-shot nudge, like every block here
  2. sprint complete, no sprint_end event → block "run /xp-sprint-review"

Reviewing-state alone fires the gate (incremental teammate accept):
teammates self-promote in-progress -> reviewing on clean exit without
orchestrator Edits, so the .accept marker never arms; reviewing IS the
canonical "work needs acceptance" signal.

Sprint retrospective is NOT part of the Stop cascade. It runs at the
start of the next session via retrospective.py, which detects a
dangling sprint_end and branches to sprint-retro prep.

Common deferrals (review cycle active, teammates active) apply to all
steps so the main agent can continue its current workflow without being
blocked mid-cycle.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import branching
import coordination
import identity
import markers
import sprint_state
import worktree
from event_schema import EVENT_TYPE_SPRINT, SPRINT_ACTION_END
from sprint_schema import UNDER_ACCEPTANCE_STORY_STATUSES
from sprint_status import (
    has_active_stories_data,
    has_in_progress_stories_data,
    has_under_acceptance_stories_data,
)

_WATERMARK_ID = "sprint-stop-gate"

_ACCEPT_MESSAGE = (
    "Stories need acceptance. Run /xp-accept to verify "
    "acceptance criteria before stopping."
)

_IN_PROGRESS_ACCEPT_MESSAGE = "Run /xp-accept once done, or just stop."

_UNREADABLE_MESSAGE = (
    "sprint.json cannot be read ({exc}). Every sprint gate is blind until it is "
    "repaired — run smm/sprint_cli.py create, or restore it from backup."
)

_REVIEW_MESSAGE = (
    "Sprint complete. Run /xp-sprint-review to review what shipped before stopping."
)


def _deferred(smm_dir: Path, agent_id: str, cwd: str) -> bool:
    """Return True if we should defer blocking (mid-workflow, teammates active)."""
    # Mid-AskUserQuestion dialogue — cheapest check, most common interactive hit
    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return True
    # Mid-/xp-accept: the skill arms ACCEPT_IN_FLIGHT at preload. While armed,
    # suppress the accept gate so it never tells the agent to run the skill it
    # is already inside (e.g. while awaiting background acceptance tests). The
    # consume is hook-driven at accept's terminal dispatch — accept_terminal
    # drains it on the /xp-schedule or /xp-sprint-review completion that ends
    # the skill (the old state-derived drain here could never fire mid-sprint
    # once /xp-schedule promoted the next story). The SessionStart sweep is the
    # abandonment backstop.
    if markers.marker_exists(smm_dir, markers.ACCEPT_IN_FLIGHT):
        return True
    # Defer only while a review is mid-flight (simplify_done set,
    # quality_review_done not yet). The predicate — incl. the self-find
    # invariant — lives in markers.review_mid_cycle, shared with
    # close_cycle_stop_gate so the rule has one home.
    if markers.review_mid_cycle(smm_dir, agent_id):
        return True
    if coordination.has_active_teammates(smm_dir, agent_id):
        return True
    # In-place teammate: no worktree is registered for it, so has_live_teammates
    # below is blind to it. Name-free and liveness gated — it defers while EITHER
    # the supervising spawn_teammate still HOLDS its per-name flock (the kernel
    # releases that however the process dies, so a recycled pid can no longer
    # wedge the name) or the `claude` child it launched is still alive (the child
    # OUTLIVES a SIGKILLed supervisor, so the lock alone would un-defer
    # mid-flight). Falls through once both are gone rather than deferring forever
    # on a leaked marker. Reaps the markers it proves fully dead — this call is
    # not side-effect-free.
    if worktree.has_live_in_place_teammate(smm_dir):
        return True
    # Live teammate worktrees: covers the spawn-to-first-write window where
    # coordination.json isn't populated yet.
    return bool(cwd) and worktree.has_live_teammates(cwd)


def _has_sprint_end_event(events: list[dict], sprint_id: str) -> bool:
    """Return True if a sprint_end event for the given sprint_id exists."""
    for event in reversed(events):
        if event.get("type") != EVENT_TYPE_SPRINT:
            continue
        metadata = event.get("metadata") or {}
        if (
            metadata.get("action") == SPRINT_ACTION_END
            and metadata.get("sprint_id") == sprint_id
        ):
            return True
    return False


def _in_progress_has_work(smm_dir: Path, cwd: str) -> bool:
    """True when the in-progress story branch has commits ahead of its base.

    The ACCEPT marker arms on the first Edit of an in-progress story —
    before any commit — so marker presence alone over-fires the accept
    gate against an empty branch right after assign. Refine with a real
    commits-ahead check. Without a usable cwd (missing, or not a real
    directory) we can't measure it, so assume work exists (fire —
    preserve the prior behavior). A git failure (commits_ahead -> None)
    is likewise treated as "has work" so a real un-accepted story is
    never silently skipped.
    """
    if not cwd or not Path(cwd).is_dir():
        return True
    base = branching.get_story_base_branch(smm_dir, cwd)
    n = branching.commits_ahead(cwd, base)
    return n != 0


def _has_checkable_proof(story: dict) -> bool:
    """True when /xp-accept has something to check for *story*.

    Command presence is the primary route — `_acceptance_execution` states the
    rule as "gate on command PRESENCE, not on type" — and a manual block's
    `steps` are the documented walkthrough, which is declared proof even though
    nothing runs.

    Absence is NOT the discriminator, and that distinction is the whole point:
    `type` is the only required key, so `{"type": "manual"}` carrying neither a
    command nor steps is schema-valid and declares nothing. Keying on
    absent/null would read that shape as proof.

    ANY, never EACH — read the silence narrowly. No per-AC verified state
    exists, so one declared command over a story with five acceptance criteria
    answers True here. True means "something is declared", NOT "the criteria
    are proven": a caller that reports the un-named stories as verified would
    be making the same claim this predicate was written to stop making.
    """
    block = story.get("acceptance_execution")
    if not isinstance(block, dict):
        return False
    if block.get("command") or block.get("commands"):
        return True
    steps = block.get("steps")
    if not isinstance(steps, list):
        return False
    return any(isinstance(step, str) and step.strip() for step in steps)


def _accept_message(firing: list[dict], base: str) -> str:
    """The accept message for *base*, naming any firing story nothing can check.

    Scoped to the stories that actually FIRED the branch, never the whole
    sprint: a done story has left the accept window and is nobody's outstanding
    proof. *base* is returned byte-for-byte when every firing story declares
    proof, so the working direction is untouched. *base* is the branch's own
    constant (``_ACCEPT_MESSAGE`` or ``_IN_PROGRESS_ACCEPT_MESSAGE``) — the
    caller picks it, this function only appends the unprovable-story suffix.
    """
    unprovable = sorted(
        story.get("id", "") for story in firing if not _has_checkable_proof(story)
    )
    if not unprovable:
        return base
    return (
        f"{base} No proof is declared for "
        f"{', '.join(unprovable)} — nothing there can be checked."
    )


def _compute_block_message(smm_dir: Path, sprint_data: dict, cwd: str) -> str | None:
    """Return the first triggered cascade block message, or None.

    Uses the ``_data`` predicate variants throughout so the sprint dict
    loaded by the caller is reused — no double-load on the disk for a
    single Stop hook invocation.
    """
    # Cascade step 1: accept gate. Any UNDER_ACCEPTANCE story (reviewing
    # or closing) fires (Option A): both are mid-accept-window states
    # where the user must run /xp-accept (or finish the in-flight close)
    # before stopping. These carry committed+merged work, so they fire
    # unconditionally — only the in-progress+marker path is refined below.
    stories = sprint_data["stories"]
    if has_under_acceptance_stories_data(sprint_data):
        return _accept_message(
            [s for s in stories if s.get("status") in UNDER_ACCEPTANCE_STORY_STATUSES],
            _ACCEPT_MESSAGE,
        )
    if has_in_progress_stories_data(sprint_data):
        if markers.marker_exists(smm_dir, markers.ACCEPT) and _in_progress_has_work(
            smm_dir, cwd
        ):
            return _accept_message(
                [s for s in stories if s.get("status") == "in-progress"],
                _IN_PROGRESS_ACCEPT_MESSAGE,
            )
        return None

    # Cascade step 2: sprint-review gate — requires sprint complete.
    if has_active_stories_data(sprint_data):
        return None

    sprint_id = sprint_data.get("sprint_id") or ""
    if not sprint_id:
        return None

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if not _has_sprint_end_event(events, sprint_id):
        return _REVIEW_MESSAGE
    return None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message for the first triggered cascade step, or None."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Missing and unreadable are different answers, and `load_sprint` already
    # tells them apart: None for absence, SprintCorruptError (a ValueError) for
    # bad bytes / bad JSON / schema failure, OSError for a symlinked path.
    # Catching both is the same pairing pre_tool_write uses for this case, and
    # for the same reason — every sprint gate is blind on state it cannot read,
    # so an uncaught raise here is a hook that errored, which is a hook that
    # released. Absence stays a release: turning it into a block would fire on
    # every project that has never run a sprint.
    #
    # Returned BEFORE the `_deferred` check below, deliberately. A live teammate
    # or a mid-review cycle is a reason to postpone an ordinary prompt; it is not
    # a reason to stop caring that sprint state is unreadable. `stop_hook_active`
    # above already prevents a wedge.
    try:
        sprint_data = sprint_state.read_sprint_content(smm_dir)
    except (ValueError, OSError) as exc:
        return _UNREADABLE_MESSAGE.format(exc=exc)
    if sprint_data is None:
        return None

    cwd = input_data.get("cwd", "") or ""
    block_message = _compute_block_message(smm_dir, sprint_data, cwd)
    if block_message is None:
        return None

    # Defer if mid-workflow — only pay the cost when we'd otherwise block
    agent_id = identity.resolve_agent_id(input_data)
    if _deferred(smm_dir, agent_id, cwd):
        return None

    return block_message


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Sprint lifecycle gate — action required.")
    sys.exit(0)
