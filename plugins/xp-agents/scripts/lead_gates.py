#!/usr/bin/env python3
"""The lead-only marker gates enforced by the Write/Edit/MultiEdit PreToolUse hook.

Extracted from pre_tool_write.py when the state-derived assign gate pushed it
past the 500-line cap. The seam is the one the test suite already drew:
tests/hooks/test_lead_gates.py covers exactly this module.

Every gate here is a MARKER gate: something arms it by writing a marker into the
shared SMM dir, and it blocks the lead's writes until it is disarmed. A gate that
can only be disarmed by the act it demands is a plain marker gate; one that the
world can make moot behind its back needs an `active_when` predicate so it can
self-clear. See _LeadGate.

A marker-FREE gate (the schedule gate) does not belong here — it lives inline in
pre_tool_write.run, which is where its state is already loaded.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity
import markers
import sprint_state
import sprint_status
import worktree


class _LeadGate(NamedTuple):
    """A marker gate that applies to the LEAD only.

    *active_when* makes a gate state-derived: the marker ARMS it, the predicate
    SELF-CLEARS it. Without one, a gate blocks for as long as its marker exists,
    which is a marker-block gate — it keeps demanding an action after the state
    that made the action necessary has moved on. With one, the gate goes quiet
    on its own the instant there is nothing left to do, and — because
    check_lead_gates DELETES the marker rather than merely skipping it — cannot
    spring back when unrelated state changes later.

    A gate whose demanded action is the only thing that could clear it (a plan
    review, a user's answer) has no state to derive from and leaves this None;
    it then costs nothing beyond the marker stat.
    """

    marker: markers.MarkerDef
    reason: str
    short: str
    plan_files_exempt: bool
    active_when: Callable[[dict, Path], bool] | None = None


def _story_is_spawned(story: dict, live_branches: dict[str, str]) -> bool:
    """True when *story*'s OWN teammate is live — matched on story id AND branch.

    The id alone is not an identity. Story ids repeat every sprint, and a
    worktree left registered by an abandoned close keeps its
    `worktree-story-003` directory name forever — so an id-only match reads
    LAST sprint's story-003 worktree as THIS sprint's spawned teammate. And
    because check_lead_gates CONSUMES the marker on a False, that misread does
    not merely skip the gate once: it DELETES it, permanently, and nothing
    re-arms it. /xp-assign is then never demanded, no branch is cut, no teammate
    is spawned, and the lead silently implements the story in the main checkout
    with its commits misattributed.

    The branch is what disambiguates, because it carries the slug
    (`<user>/story-003-perf-timers` vs `<user>/story-003-tools-remember`).
    /xp-assign records it on the story (branching.create_story_branch ->
    sprint_store.set_story_branch) in Step 2, BEFORE the Step 4 spawn, so by the
    time a worktree can exist the story already names the branch it must be on.
    Exactly the defence `spawn_prompt.load_prompt_for_story` makes for the prompt
    file, applied to the worktree.

    Both sides must be NON-EMPTY. A story with no recorded branch cannot have
    been spawned (assign cuts the branch first), and a worktree on a detached
    HEAD reports no branch — letting `"" == ""` pass would re-open the id-only
    hole for exactly the states that are least trustworthy.
    """
    branch = story.get("branch_name") or ""
    return bool(branch) and live_branches.get(story.get("id", "")) == branch


def _unspawned_teammate_story_exists(input_data: dict, smm_dir: Path) -> bool:
    """True while some in-progress teammate story still has no live worktree.

    This is the assign gate's remit, stated positively: /xp-assign exists to
    create a story's branch and spawn its teammate, one spawn per invocation.
    So there is something to assign exactly while a teammate story is promoted
    but not yet spawned — the same target /xp-assign's own preload derives as
    RECOMMENDED_TIER_STORY (the first un-spawned story in batch order).

    It goes false the moment the last teammate is spawned, and stays false
    through accept and close. A story merely SCHEDULED does not revive it:
    promoting a frontier is /xp-schedule's business, and its own state-derived
    gate covers that window.

    FAILS CLOSED, on EVERY read it makes — which is the licence check_lead_gates
    needs to DELETE the marker on a False. There are three reads and each one
    blocks rather than guesses:

      * `git worktree list` errors -> no live worktrees -> every story reads
        un-spawned -> block.
      * sprint.json is corrupt/unreadable -> we cannot tell -> block. `load_sprint`
        RAISES (SprintCorruptError, a ValueError; OSError on a symlink) rather
        than returning None, and an uncaught raise here is not a block but an
        ALLOW: the hook dies with a traceback and exits 1, which PreToolUse
        treats as a non-blocking error — the write lands, and the QUESTION gate
        further down _LEAD_GATES is never even reached. Note this is deliberately
        NOT `load_sprint_fail_open`: degrading a bad read to None would make it
        indistinguishable from "no sprint", which returns False and EATS the
        marker. On the Write hot path a bad read must fail closed.
      * a stale same-id worktree from a previous sprint -> not a branch match ->
        reads un-spawned -> block (see _story_is_spawned).

    False therefore means the sprint positively says there is nothing to assign,
    never "could not tell".

    HOT PATH. Reached only after the marker stat and the teammate exemption; the
    stale case returns before touching git. ONE `git worktree list` answers every
    story — find_teammate_worktree_for_story re-runs it per call, costing a
    subprocess PER STORY on every Write/Edit. See check_lead_gates.
    """
    try:
        sprint_data = sprint_state.read_sprint_content(smm_dir)
    except (ValueError, OSError):
        return True  # cannot tell -> stay armed, stay blocking
    if sprint_data is None:
        return False

    promoted = sprint_status.select_promoted_teammate_stories(
        sprint_data.get("stories", [])
    )
    if not promoted:
        return False  # the stale case — settled without paying for git

    cwd = input_data.get("cwd", ".")
    live_branches = worktree.live_teammate_branch_by_story(cwd)
    return any(not _story_is_spawned(story, live_branches) for story in promoted)


# Checked in order; the first armed gate blocks. Teammates are exempt from ALL
# of them. Every marker lives in the SHARED SMM dir and a teammate can clear
# none of them: it never plans, it is dispatched BY /xp-assign, and — running
# headless — it has no user to answer an AskUserQuestion. So gating a teammate
# forbids the parallel pipeline's whole purpose (the lead plans/assigns story
# N+1 while a teammate executes story N) and strands the teammate mid-story
# with no recovery path. A gate added to this table inherits the exemption by
# construction; the hand-rolled gates this replaces defaulted the other way,
# which is how the plan gate came to forbid the pipeline unnoticed for months.
_LEAD_GATES: tuple[_LeadGate, ...] = (
    _LeadGate(
        markers.PLAN_AWAITING_REVIEW,
        "Run /xp-review-plan before writing code. "
        "Plan review extracts assumptions, decisions, and risks for the SMM.",
        "Plan review required before implementation.",
        plan_files_exempt=True,
    ),
    _LeadGate(
        markers.ASSIGN_PENDING,
        "Run /xp-assign to create the next story's branch and spawn its "
        "teammate (per-story pipeline — one spawn per invocation) "
        "before writing code.",
        "Work assignment required before implementation.",
        plan_files_exempt=True,
        active_when=_unspawned_teammate_story_exists,
    ),
    _LeadGate(
        markers.QUESTION_GATE,
        "A blocking question needs the user's answer. AskUserQuestion is "
        "the ONLY way to clear this — it records the answer and lifts the "
        "gate. Do NOT record a decision/status event resolving the question "
        "id: it does not clear the gate and fabricates an answer the user "
        "never gave.",
        "Blocking question requires user answer.",
        plan_files_exempt=False,
    ),
)


def check_lead_gates(
    input_data: dict, smm_dir: Path | None, is_plan_file: bool
) -> None:
    """Raise BlockedError for the first armed AND active lead-only gate.
    Teammates exempt.

    Three checks, in strictly increasing cost, and the order is the design:

    1. the marker stat — run() is on the hot path for every Write/Edit/MultiEdit,
       and the common case (lead, nothing armed) must not pay for a cwd parse, an
       env read, or a subprocess whose answer nothing consumes;
    2. the teammate probe — memoized, because every lead gate shares one
       exemption, so one probe answers all three;
    3. `active_when`, the state-derived predicate — last, because it can shell out
       to `git worktree list`. A teammate is exempt from every gate regardless of
       what the predicate would say, and teammates write constantly while the
       assign marker is armed (the lead plans story N+1 while they execute story
       N), so settling the exemption first keeps that subprocess off their path.

    An armed gate whose predicate says there is nothing left to do has its marker
    CONSUMED, not merely skipped: deleting it is what makes the gate self-clearing
    rather than inert, since an inert marker springs back the instant state
    satisfies the predicate again. See _LeadGate.active_when. Residual, not closed
    here: the consume needs a lead write to fire, so a marker that goes moot and
    sees NO lead write before the next teammate frontier is promoted still blocks
    that frontier's pre-plan window. Closing it needs the marker scoped to the
    story it was armed for — subagent_stop's side of the contract.

    *smm_dir* is handed to the probe rather than left to its env fallback: that
    leg reads $SMM_DIR and fails CLOSED without it, which would misread a live
    in-place teammate as the lead and over-gate it.
    """
    if smm_dir is None:
        return

    is_teammate: bool | None = None
    for gate in _LEAD_GATES:
        if gate.plan_files_exempt and is_plan_file:
            continue
        if not markers.marker_exists(smm_dir, gate.marker):
            continue
        if is_teammate is None:
            is_teammate = identity.is_worktree_teammate(input_data, smm_dir)
        if is_teammate:
            return  # a teammate can clear none of these gates
        if gate.active_when is not None and not gate.active_when(input_data, smm_dir):
            # Armed, but the state it was armed for moved on. DELETE the marker,
            # don't merely skip it: a skipped marker stays on disk and springs
            # the gate back the moment state satisfies the predicate again — for
            # the assign gate, the next /xp-schedule promoting a teammate
            # frontier, demanding /xp-assign BEFORE the plan review meant to arm
            # it. Safe because the predicate fails CLOSED.
            markers.marker_consume(smm_dir, gate.marker)
            continue
        raise _common.BlockedError(gate.reason, gate.short)
