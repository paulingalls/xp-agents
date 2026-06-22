#!/usr/bin/env python3
"""Stop command hook: unified sprint lifecycle gate.

Replaces accept_gate.py. Handles the sprint cascade (accept → review):
  1. reviewing stories OR (in-progress + ACCEPT marker) → block "run /xp-accept"
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

_REVIEW_MESSAGE = (
    "Sprint complete. Run /xp-sprint-review to review what shipped before stopping."
)

_REVIEW_FLAGS = markers._REVIEW_FLAGS


def _deferred(smm_dir: Path, agent_id: str, cwd: str) -> bool:
    """Return True if we should defer blocking (mid-workflow, teammates active)."""
    # Mid-AskUserQuestion dialogue — cheapest check, most common interactive hit
    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return True
    # Mid-/xp-accept: the skill arms ACCEPT_IN_FLIGHT at preload and consumes
    # it at its terminal handoff. While armed, suppress the accept gate so it
    # never tells the agent to run the skill it is already inside (e.g. while
    # awaiting background acceptance tests). A leak self-heals via the
    # SessionStart stale-marker sweep.
    if markers.marker_exists(smm_dir, markers.ACCEPT_IN_FLIGHT):
        return True
    cycle = markers.read_review_cycle(smm_dir, agent_id)
    flags = [bool(cycle.get(f)) for f in _REVIEW_FLAGS]
    if any(flags) and not all(flags):
        return True
    if coordination.has_active_teammates(smm_dir, agent_id):
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
    if has_under_acceptance_stories_data(sprint_data):
        return _ACCEPT_MESSAGE
    if has_in_progress_stories_data(sprint_data):
        if markers.marker_exists(smm_dir, markers.ACCEPT) and _in_progress_has_work(
            smm_dir, cwd
        ):
            return _ACCEPT_MESSAGE
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

    sprint_data = sprint_state.read_sprint_content(smm_dir)
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
