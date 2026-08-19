#!/usr/bin/env python3
"""What a refused call does to each preload mutation site — data only, no tests.

The third piece of one measurement, and the seam is the same one that produced
`_preload_mutation_scan`: that module is the SCAN (which sites exist),
`tests/skills/test_preload_side_effects.py` is the CHECK (every site classified,
no entry dead, nothing still exposed), and this is the VERDICT TABLE they meet
over. Split out when the check file crossed the tree-wide 500-line cap — the
table grows whenever a preload gains a mutation, the check only when the rule
changes, so they were growing for different reasons in one file.

Read `_preload_mutation_scan`'s docstring for what the population does and does
not include; read the check module's for why a classification is about a
REFUSAL rather than about whether the mutation is a good idea.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from _preload_mutation_scan import _DEFINITION_TARGET, Site
from conftest import _PLUGIN_ROOT

_SKILLS_DIR = _PLUGIN_ROOT / "skills"

# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: Mutates state that gates a REAL operation, and running the preload for a call
#: that was refused spends it. No entry carries it today —
#: `TestNoSiteIsStillExposed` is what makes that a checked claim — and the
#: constant stays so a NEW site can be classified honestly and fail that test.
EXPOSED = "exposed"

#: Was EXPOSED. `preload_injection.run()` now computes the gate verdict itself
#: and declines to run the preload at all when the call will be refused.
GUARDED = "guarded"

#: Survives a refusal without consequence, for the reason recorded beside it.
HARMLESS = "harmless"


@dataclass(frozen=True)
class Verdict:
    classification: str
    reason: str


def _guarded(reason: str) -> Verdict:
    """Was EXPOSED, and is reached no more on the gate-refusal path.

    `preload_injection.run()` computes `pre_tool_skill`'s own block verdict —
    by calling the shipped predicates, not by respelling them — before it
    resolves the invocation, and returns None when either fires. The preload
    process is never started, so every mutation in the script is skipped, not
    just the one this entry names.

    The reason is kept as written while the site was exposed: what a refusal
    WOULD cost is the fact that makes the guard load-bearing, and a reader who
    only sees "guarded" has no way to weigh removing it.
    """
    return Verdict(GUARDED, reason)


_DEFINITION = Verdict(
    HARMLESS,
    "A shell function definition, not a call site: sourcing it mutates nothing. "
    "Registered rather than filtered out so the population stays the size it "
    "looks. Its call sites are classified per-script below.",
)

_SWEPT_AT_SESSION_START = (
    "Session-scoped and unconditionally consumed by "
    "`session_markers._STALE_SESSION_MARKERS` at every fresh SessionStart, so "
    "an arm left by a refused call cannot outlive the session that made it. "
)

_CLOSE_CYCLE_ARM = (
    "Arms the close-cycle Stop gate. An arm with no close behind it is not "
    "swept — `close_cycle_abandonment.record_abandonment` OWNS this marker and "
    "files a high-severity abandonment concern for it at the next SessionStart, "
    "which a later close's own count then reads as a reason to abort. AC2 names "
    "this case: no armed close cycle may survive a refusal."
)

_ORPHAN_CLOSE_EVENT = (
    "Appends a `close_started` status event for a close that never ran. The "
    "orphaned-event problem is explicitly out of scope for story-019 and "
    "recorded as its own finding; what IS in scope is that the gate-refusal "
    "path no longer reaches the emission at all."
)

_CLOSE_RESTART_RECORD = (
    "Records an ABANDONED previous close cycle: `record_abandonment` appends a "
    "high-severity concern and then consumes CLOSE_CYCLE_ACTIVE. Run for a call "
    "that was refused, it can disarm a close that is live in another window — "
    "the owner-liveness read falls back to age whenever the owning session's "
    "heartbeat cannot be read, and the SMM is shared across worktrees. The "
    "record is also the input Step 6's abort-default weighs, so a refused call "
    "feeding it moves a later close's verdict."
)

_REGISTRY: dict[Site, Verdict] = {
    # -- the shared library every preload sources ---------------------------
    Site("_preload_markers.sh", "consume_marker", _DEFINITION_TARGET): _DEFINITION,
    Site("_preload_markers.sh", "write_marker", _DEFINITION_TARGET): _DEFINITION,
    Site(
        "_preload_base.sh", "emit_close_started_event", _DEFINITION_TARGET
    ): _DEFINITION,
    Site("_preload_base.sh", "append.sh", ""): _guarded(_ORPHAN_CLOSE_EVENT),
    Site("_preload_base.sh", "rm -f", "$out"): Verdict(
        HARMLESS,
        "Deletes the render tempfile this same function just created, on its "
        "own failure path. Nothing outside the failed call ever held the path.",
    ),
    Site("_preload_base.sh", "rm -f", "{}"): Verdict(
        HARMLESS,
        "The stale-render-tempfile sweep. Its patterns are per-invocation "
        "render artifacts that no gate reads, and the one cross-step artifact "
        "that must NOT be in scope is pinned by `test_preload_sweep_scope.py`. "
        "A refusal makes the sweep no more destructive than a normal run.",
    ),
    # -- xp-accept ----------------------------------------------------------
    Site("xp-accept/scripts/preload.sh", "consume_marker", "ACCEPT"): _guarded(
        "Consumes the run-accept-before-mark-done gate that "
        "`pre_tool_bash` enforces. Spent on a refused call, the next mark-done "
        "sails through with no acceptance ever verified. The consume must stay "
        "HERE and at preload start — it is load-bearing self-unblocking for "
        "/xp-accept's own Step 4 `update-story done` — so the only safe fix is "
        "not to run the preload for a call that will be refused.",
    ),
    Site("xp-accept/scripts/preload.sh", "write_marker", "ACCEPT_IN_FLIGHT"): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "Its only mid-session effect is to DEFER the "
        "sprint stop gate's 'run /xp-accept' nudge — a suppressed reminder, not "
        "a spent gate: nothing becomes permitted that was forbidden.",
    ),
    # -- xp-assign: no entry, and that is the point -------------------------
    # It had two — the `--consume-gate` option parse and the
    # `consume_marker ASSIGN_PENDING` it enabled — and both were DELETED with
    # their sites (story-021) rather than reclassified, because
    # `test_no_registry_entry_is_dead` treats an entry matching no site as the
    # defect it is. The gate discharges from sprint state now, so the assign
    # preload mutates nothing a refusal or a read could spend.
    # -- the four close preloads --------------------------------------------
    Site("xp-free-close/scripts/preload.sh", "--detector", "close_restart"): _guarded(
        _CLOSE_RESTART_RECORD
    ),
    Site("xp-free-close/scripts/preload.sh", "--arm-only", ""): _guarded(
        _CLOSE_CYCLE_ARM
    ),
    Site(
        "xp-free-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ACTIVE"
    ): _guarded(_CLOSE_CYCLE_ARM + " This is the fallback arm for the line above."),
    Site("xp-free-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ID"): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "It only STAMPS concerns raised during a "
        "close; with no close running nothing is stamped.",
    ),
    Site(
        "xp-free-close/scripts/preload.sh", "emit_close_started_event", "free"
    ): _guarded(_ORPHAN_CLOSE_EVENT),
    Site("xp-plan-close/scripts/preload.sh", "--detector", "close_restart"): _guarded(
        _CLOSE_RESTART_RECORD
    ),
    Site("xp-plan-close/scripts/preload.sh", "--arm-only", ""): _guarded(
        _CLOSE_CYCLE_ARM
    ),
    Site(
        "xp-plan-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ACTIVE"
    ): _guarded(_CLOSE_CYCLE_ARM + " This is the fallback arm for the line above."),
    Site("xp-plan-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ID"): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "It only STAMPS concerns raised during a "
        "close; with no close running nothing is stamped.",
    ),
    Site(
        "xp-plan-close/scripts/preload.sh", "emit_close_started_event", "plan"
    ): _guarded(_ORPHAN_CLOSE_EVENT),
    Site("xp-sprint-close/scripts/preload.sh", "--detector", "close_restart"): _guarded(
        _CLOSE_RESTART_RECORD
    ),
    Site("xp-sprint-close/scripts/preload.sh", "--arm-only", ""): _guarded(
        _CLOSE_CYCLE_ARM
    ),
    Site(
        "xp-sprint-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ACTIVE"
    ): _guarded(_CLOSE_CYCLE_ARM + " This is the fallback arm for the line above."),
    Site(
        "xp-sprint-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ID"
    ): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "It only STAMPS concerns raised during a "
        "close; with no close running nothing is stamped.",
    ),
    Site(
        "xp-sprint-close/scripts/preload.sh", "emit_close_started_event", "sprint"
    ): _guarded(_ORPHAN_CLOSE_EVENT),
    Site(
        "xp-story-close/scripts/preload.sh", "write_marker", "CLOSE_CYCLE_ID"
    ): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "Story-close does not arm the Stop gate at "
        "all (it is not in `close_cycle_stop_gate._GATE_ARMING_CLOSE_MODES`), "
        "so this id is the only close-cycle state it writes.",
    ),
    Site(
        "xp-story-close/scripts/preload.sh", "emit_close_started_event", "story"
    ): _guarded(_ORPHAN_CLOSE_EVENT),
    Site("xp-story-close/scripts/preload.sh", "rm -f", "$err_file"): Verdict(
        HARMLESS,
        "Deletes the `mktemp` stderr capture created three lines above, inside "
        "the same function. No other process can name the path.",
    ),
    # -- xp-review-plan -----------------------------------------------------
    Site(
        "xp-review-plan/scripts/preload.sh", "consume_marker", "PLAN_AWAITING_REVIEW"
    ): _guarded(
        "Clears `.plan-awaiting-review` on the MISFIRE branch only — the marker "
        "names a plan file that no longer exists, so no review could satisfy the "
        "gate and a lead left holding it is write-blocked with no way out. "
        "Garbage collection of an unsatisfiable gate, not a discharge: the "
        "discharge lives at the plan reviewer's completion "
        "(`subagent_stop._handle_plan_review_done`) since story-021. Still worth "
        "the guard, because a refused call reaching it un-arms a gate the lead "
        "never got to satisfy — but the plan is gone either way, so what is lost "
        "is the nudge to re-enter plan mode rather than the review itself.\n"
        "Spelled with the helper rather than `rm -f` deliberately: it is the "
        "marker convention, and it keeps this act distinguishable from the "
        'discharge that was removed, which had `rm -f "$MARKER"`\'s key. While '
        "both spellings matched, this entry absorbed a re-added discharge — see "
        "`TestTwoSitesInOneScriptStayDistinguishable`.",
    ),
    Site("xp-review-plan/scripts/preload.sh", "rm -f", "$LAST_PLAN_PATH_FILE"): Verdict(
        HARMLESS,
        "Clears `.last-plan-path`, a POINTER to the previously reviewed plan, "
        "and only on the branch that already reported PLAN_FILE_ERROR. No gate "
        "reads it; the next successful run rewrites it.",
    ),
    Site(
        "xp-review-plan/scripts/preload.sh", ">SMM_DIR", "${SMM_DIR}/.last-plan-path"
    ): Verdict(
        HARMLESS,
        "Writes the same pointer. Overwritten by the next run and read by "
        "nothing that gates an operation, so a value written for a call that "
        "never happened costs one stale suggestion at most.",
    ),
    # -- xp-sprint-review ---------------------------------------------------
    Site("xp-sprint-review/scripts/preload.sh", "rm -f", "$REVIEW_INPUT"): Verdict(
        HARMLESS,
        "Deletes the `mktemp` file this same run created two lines above, on "
        "its own failure path. Nothing else has been told the path.",
    ),
    # -- xp-work-selection --------------------------------------------------
    Site(
        "xp-work-selection/scripts/preload.sh", "write_marker", "NEEDS_HOUSEKEEPING"
    ): _guarded(
        "Arms `housekeeping_stop_gate`, which then BLOCKS Stop for everyone "
        "sharing the SMM until the housekeeper runs and consumes it. Armed by a "
        "refused call, a gate exists for work nobody asked for — and the SMM is "
        "shared across worktrees, so a teammate's refusal gates the lead.",
    ),
    Site(
        "xp-work-selection/scripts/preload.sh", "write_marker", "HOUSEKEEPING_ARMED"
    ): Verdict(
        HARMLESS,
        _SWEPT_AT_SESSION_START + "It is the once-per-session RECORD that makes "
        "the arm above decidable, and it gates nothing on its own — its only "
        "effect is to suppress a second arm in the same session.",
    ),
}
