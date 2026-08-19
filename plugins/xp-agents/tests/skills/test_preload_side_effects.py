#!/usr/bin/env python3
"""Every state a preload mutates BY RUNNING, classified against a refusal.

Since story-013 a skill's preload state is delivered by `preload_injection.py`,
a `PreToolUse` handler sitting on the same entry as `pre_tool_skill.py` — which
can BLOCK the invocation. Hooks on one entry run in parallel, so the injecting
handler cannot observe the refusal. It therefore used to run the preload anyway,
and a preload that mutates shared state by running spent that state on a call
that never happened: a teammate blocked from a lead-owned skill silently consumed
the lead's gate.

This module is the measurement, made durable. It enumerates the mutation sites
rather than listing them, so the leg that matters is "the NEXT one cannot arrive
unclassified" — a new preload that consumes a marker fails this suite until
someone says, in `_REGISTRY`, what a refusal does to it.

The scan itself lives in `_preload_mutation_scan`, split off at the 500-line
cap. Read its docstring for what it sees and — the part that matters — what it
does not: it is a verb scan over shell text, blind to the Python those scripts
shell out to.

The classification is about a REFUSAL, not about whether the mutation is good.
`GUARDED` does not mean "cannot happen"; it means the gate-refusal path no longer
reaches it. The paths no predicate can see — a user declining the permission
prompt, a refusal the harness invents for its own reasons — still run the
preload, and `TestResidueThisStoryDoesNotClose` says so out loud.
"""

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import pre_tool_skill
import preload_injection
from _preload_mutation_scan import _DEFINITION_TARGET, Site, scan_mutation_sites
from conftest import _PLUGIN_ROOT, _SMMTestCase

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
    Site("xp-review-plan/scripts/preload.sh", "rm -f", "$MARKER"): _guarded(
        "Deletes `.plan-awaiting-review`, the gate saying a plan still needs "
        "review. Consumed on a refused call, the plan is silently treated as "
        "reviewed and the next invocation reports no plan at all.",
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


class TestEveryMutationSiteIsClassified(unittest.TestCase):
    """Completeness, in both directions.

    Only completeness — NOT "nothing is exposed". A site classified EXPOSED
    passes here, which is what let this class land in the increment before the
    guard did. The stronger claim is `TestNoSiteIsStillExposed`.
    """

    def test_no_mutation_site_is_unclassified(self):
        unclassified = sorted(scan_mutation_sites(_SKILLS_DIR) - set(_REGISTRY))
        self.assertEqual(
            unclassified,
            [],
            "preload mutation sites with no _REGISTRY entry — each one runs "
            "on a call the gate beside the injection hook may refuse, so say "
            "what a refusal does to it:\n"
            + "\n".join(f"  {s.script}: {s.verb} {s.target}" for s in unclassified),
        )

    def test_no_registry_entry_is_dead(self):
        """A pin whose non-match reads as success is the class story-017 landed
        to stop. An entry for a site that no longer exists proves nothing and
        looks exactly like coverage."""
        dead = sorted(set(_REGISTRY) - scan_mutation_sites(_SKILLS_DIR))
        self.assertEqual(
            dead,
            [],
            "_REGISTRY entries matching no site in the shipped preloads:\n"
            + "\n".join(f"  {s.script}: {s.verb} {s.target}" for s in dead),
        )

    def test_every_entry_carries_a_reason(self):
        for site, verdict in _REGISTRY.items():
            with self.subTest(site=site):
                self.assertIn(verdict.classification, (EXPOSED, GUARDED, HARMLESS))
                self.assertGreater(len(verdict.reason), 30, "reason is a stub")


class TestTheScanIsNotVacuous(unittest.TestCase):
    """A scan that found nothing would pass every assertion above forever."""

    def test_the_shipped_surface_yields_sites_from_more_than_one_script(self):
        sites = scan_mutation_sites(_SKILLS_DIR)
        self.assertGreater(len(sites), 20, "the scan went blind")
        self.assertGreater(len({s.script for s in sites}), 5)

    def test_a_newly_introduced_consume_is_named(self):
        """The leg that matters: the NEXT preload cannot slip one in."""
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "xp-newcomer" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "preload.sh").write_text(
                "#!/bin/bash\n# consume_marker IN_A_COMMENT\nconsume_marker FOO\n",
                encoding="utf-8",
            )
            sites = scan_mutation_sites(Path(tmp))
        self.assertEqual(
            sites, {Site("xp-newcomer/scripts/preload.sh", "consume_marker", "FOO")}
        )

    def test_a_registry_scoped_to_one_skill_fails_on_the_others(self):
        """Non-vacuity for the completeness check itself: swap in a registry
        holding only one skill's entries and the check must go red."""
        scoped = {s for s in _REGISTRY if s.script.startswith("xp-accept/")}
        self.assertTrue(scoped, "the specimen skill left the registry")
        self.assertNotEqual(scan_mutation_sites(_SKILLS_DIR) - scoped, set())


class TestNoSiteIsStillExposed(unittest.TestCase):
    """The claim story-019 makes, checkable rather than prose.

    Withheld from the first increment on purpose — three entries were still
    genuinely exposed then, and an increment that cannot be green on its own is
    not an increment. Bounded by `TestResidueThisStoryDoesNotClose` below: this
    asserts that the GATE-refusal path reaches no exposed mutation, not that no
    refusal anywhere can.
    """

    def test_every_exposed_site_is_now_guarded(self):
        still_exposed = sorted(
            site
            for site, verdict in _REGISTRY.items()
            if verdict.classification == EXPOSED
        )
        self.assertEqual(
            still_exposed,
            [],
            "these preload mutations still run for a call the gate refuses:\n"
            + "\n".join(f"  {s.script}: {s.verb} {s.target}" for s in still_exposed),
        )

    def test_the_guard_the_flip_depends_on_is_actually_wired(self):
        """GUARDED is a claim about `preload_injection.run()`. If that guard
        ever leaves, every flipped entry above becomes a lie that reads as
        coverage — so the claim is checked against the module, not trusted."""
        self.assertTrue(
            any(v.classification == GUARDED for v in _REGISTRY.values()),
            "nothing claims to be guarded — this pin has gone vacuous",
        )
        payload = {
            "tool_input": {"skill": "xp-agents:xp-assign"},
            "cwd": "/tmp/wt/worktree-story-001",
        }
        self.assertTrue(preload_injection._refused_by_a_gate(payload))


class TestResidueThisStoryDoesNotClose(_SMMTestCase):
    """Refusals no predicate can see — named so this is not mistaken for total.

    The guard works by computing the SAME verdict the blocking hook computes,
    from state on disk. That covers every refusal the plugin itself issues, and
    nothing else:

    - A user who declines the permission prompt. No state foretells a human, and
      the decision happens after every hook on the entry has already run.
    - A refusal the harness invents for its own reasons (a cancelled turn, an
      unavailable tool). Same shape, same blindness.

    On both, the preload runs and its mutations land, exactly as before this
    story. AC3's third clause sanctions a pinned-with-reason residue; an
    unstated one would be the overclaim story-017 spent four increments removing.
    """

    def test_a_refusal_the_predicates_cannot_predict_leaves_the_preload_running(self):
        allowed = {
            "tool_input": {"skill": "xp-agents:xp-assign"},
            "cwd": str(self.smm_dir),
        }
        # Both predicates allow it, and they MUST: at hook time this payload is
        # indistinguishable from one the user is about to approve.
        self.assertFalse(preload_injection._refused_by_a_gate(allowed))
        self.assertIsNone(pre_tool_skill.teammate_block_reason(allowed))
        self.assertIsNone(pre_tool_skill.accept_evidence_block_reason(allowed))


if __name__ == "__main__":
    unittest.main()
