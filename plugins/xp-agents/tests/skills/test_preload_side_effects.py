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

Two siblings hold the other halves, both split off at the 500-line cap. The
scan is `_preload_mutation_scan` — read its docstring for what it sees and, the
part that matters, what it does not: a verb scan over shell text, blind to the
Python those scripts shell out to. The verdict table is
`_preload_side_effect_registry`, which is where a new site gets classified.

The classification is about a REFUSAL, not about whether the mutation is good.
`GUARDED` does not mean "cannot happen"; it means the gate-refusal path no longer
reaches it. The paths no predicate can see — a user declining the permission
prompt, a refusal the harness invents for its own reasons — still run the
preload, and `TestResidueThisStoryDoesNotClose` says so out loud.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import pre_tool_skill
import preload_injection
from _preload_mutation_scan import Site, scan_mutation_sites
from _preload_side_effect_registry import (
    _REGISTRY,
    _SKILLS_DIR,
    EXPOSED,
    GUARDED,
    HARMLESS,
)
from conftest import _SMMTestCase


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


class TestTwoSitesInOneScriptStayDistinguishable(unittest.TestCase):
    """A key collision inside one script is a blind spot, and it had one.

    `Site` keys on (script, verb, target) and `_REGISTRY` is keyed by `Site`, so
    two lines that spell the same verb and target in the same script collapse to
    ONE entry. xp-review-plan had exactly that: `rm -f "$MARKER"` appeared twice —
    once as garbage collection on the misfire branch, once as the gate discharge
    at the end. Removing the discharge (story-021) left the key alive via the
    other line, so the registry could not have told anyone if a
    gate-discharging `rm -f` were added back.

    Distinguished by giving the surviving act its own spelling: the misfire
    branch consumes through the marker helper, which is the convention anyway
    (one spelling of the filename, symlink refusal), and leaves `rm -f "$MARKER"`
    matching nothing — which is the shape a re-added discharge takes, since it is
    the shape the one that was removed had.

    A LIMIT, and it is the same limit one level down: two lines that both spell
    `consume_marker PLAN_AWAITING_REVIEW` would collide in turn. Read this as
    "the historical spelling is no longer absorbed", not as "no collision is
    possible".
    """

    def _shipped_review_plan_plus(self, extra: str) -> set[Site]:
        """The shipped review-plan preload with `extra` appended, scanned alone."""
        body = (_SKILLS_DIR / "xp-review-plan" / "scripts" / "preload.sh").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "xp-review-plan" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "preload.sh").write_text(body + extra, encoding="utf-8")
            return scan_mutation_sites(Path(tmp))

    def test_the_shipped_script_is_fully_classified(self):
        """The control. If the unmodified script already had an unclassified
        site, the leg below would pass on that instead of on the new line."""
        self.assertEqual(self._shipped_review_plan_plus("") - set(_REGISTRY), set())

    def test_a_readded_gate_discharge_is_named(self):
        """Re-add the discharge that was removed, in the spelling it had."""
        unclassified = self._shipped_review_plan_plus('\nrm -f "$MARKER"\n') - set(
            _REGISTRY
        )
        self.assertEqual(
            unclassified,
            {Site("xp-review-plan/scripts/preload.sh", "rm -f", "$MARKER")},
            "a gate-discharging `rm -f` came back and the registry absorbed it "
            "into a sibling entry — the story-017 defect class, a non-match "
            "reading as coverage",
        )


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

    A THIRD residue, and it is not a refusal at all: on the second harness a
    shell READ of a `SKILL.md` is what triggers the preload, so the close
    preloads still arm a close cycle and emit `close_started` for a `cat` of a
    close skill's body. story-021 moved the two gates that HAD a satisfying act
    to that act; a close cycle's arming does not have one — the act that
    satisfies it is the whole close, which the arming exists to bracket. Named
    and checked below rather than fixed here; it is recorded elsewhere as its
    own finding.
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

    def test_reading_a_close_body_still_reaches_a_close_cycle_arm(self):
        """The residue stated as a measurement, in the two halves that make it real.

        First: a plain `cat` of each close skill's body resolves to that skill,
        so the read really is what runs its preload. Second: that preload really
        does carry an arming site, and the registry's verdict on it is GUARDED —
        a claim about the gate-REFUSAL path, which a read never travels. Nothing
        here stops the arm; the point is that it is written down and would go red
        if someone deleted the residue without deleting the cause.
        """
        sites = scan_mutation_sites(_SKILLS_DIR)
        # Three of the four close skills. xp-story-close arms no close cycle of
        # its own — it runs inside the accept loop's — so naming it here would
        # assert a site it does not have.
        for skill in ("xp-free-close", "xp-plan-close", "xp-sprint-close"):
            with self.subTest(skill=skill):
                body = _SKILLS_DIR / skill / "SKILL.md"
                self.assertEqual(
                    preload_injection.skill_from_command(f"cat {body}"), skill
                )
                arms = [
                    site
                    for site in sites
                    if site.script == f"{skill}/scripts/preload.sh"
                    and site.target == "CLOSE_CYCLE_ACTIVE"
                ]
                self.assertTrue(arms, "the close-cycle arm left this preload")
                for site in arms:
                    self.assertEqual(_REGISTRY[site].classification, GUARDED)


if __name__ == "__main__":
    unittest.main()
