#!/usr/bin/env python3
"""Tests for scripts/lead_gates.py — the _LEAD_GATES table, the assign gate, and
the machinery every lead gate shares (teammate exemption, hot path, and the
`active_when` predicate that makes a marker gate self-clearing).

Split from test_pre_tool_write_gates.py, which was over the 500-line cap; the
plan and question gate suites and the accept marker stay there. Split AGAIN, for
the same reason, when the fail-closed suite grew: every "a read this gate cannot
trust must BLOCK, never allow" test now lives in test_write_gate_fails_closed.py,
which owns that seam across BOTH modules. And a THIRD time for the marker's
story scope — how the predicate tells the stories a marker was armed for from
an unrelated frontier — in test_lead_gates_story_scope.py. The fixtures all
three share are in tests/_lead_gate_fixtures.py, whose `_arm` writes the LEGACY
(pre-scope) payload and is now a legacy-compat pin for the tests here.

WHY THE ASSIGN GATE IS STATE-DERIVED. The marker alone used to block. That made
it a marker-block gate: `/xp-assign` clears the marker, but nothing cleared it
when the STATE moved on — the story it was armed for got accepted and the
marker sat there demanding an assignment that no longer existed. The project
constraint is that gates are state-derived, SELF-CLEARING, never marker-block.

The gate is armed by a marker and answers "is there anything to assign?" from
live sprint state:

    active IFF an un-spawned in-progress teammate story exists

which is exactly the target `/xp-assign`'s own preload derives, and which goes
false the instant the last teammate is spawned. Both halves are needed — a
marker-free predicate would fire before the plan review had even happened.

SUPPRESSING IS NOT SELF-CLEARING, and the difference is the point. A gate that
merely declines to fire leaves its marker on disk, so the next state that
happens to satisfy the predicate springs it back — here, the next /xp-schedule
promoting a teammate frontier, which would demand /xp-assign for a story whose
plan review has not happened yet. So a moot marker is DELETED, not skipped:
    - test_stale_marker_is_deleted_not_merely_skipped
    - test_promoting_a_teammate_frontier_cannot_resurrect_a_stale_marker
and the two guards that keep the delete honest — a live gate must never eat its
own marker, and a teammate must never eat the lead's.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lead_gates
import pre_tool_write
import worktree
from _lead_gate_fixtures import (
    BRANCH_001,
    BRANCH_002,
    SPRINT_ALL_ACCEPTED,
    SPRINT_SCHEDULED_AFTER_STALE,
    SPRINT_SOLO_IN_PROGRESS,
    SPRINT_TEAMMATE_IN_PROGRESS,
    _AssignGateTestCase,
    _lead_write,
)
from conftest import _make_write_input, _s, _sprint_json


class TestAssignGateIsLive(_AssignGateTestCase):
    """The working case. Do NOT un-gate this while fixing the stale one: the
    gate caught a real lead bypassing /xp-assign, which is exactly its job."""

    def test_unspawned_teammate_story_blocks_write(self):
        """Marker armed + a teammate story with no worktree -> block."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned():  # nothing spawned yet
            self._assert_blocks(_lead_write())

    def test_gate_self_clears_once_the_last_teammate_is_spawned(self):
        """The instant every in-progress teammate story has a worktree there is
        nothing left to assign, so the gate goes quiet — without anyone having
        to remove the marker. This is the self-clearing half."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned("story-001"):
            self._assert_allows(_lead_write())

    def test_a_blocking_gate_never_consumes_its_own_marker(self):
        """The consume fires ONLY on a moot marker. If a live gate ate its own
        marker, the very first blocked write would disarm it and the second
        would sail through — a gate that fires once is no gate at all."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned():
            self._assert_blocks(_lead_write())
            self.assertTrue((self.smm_dir / ".assign-pending").exists())
            self._assert_blocks(_lead_write())  # still armed

    def test_one_unspawned_story_among_spawned_ones_still_blocks(self):
        """A partially-spawned batch is still an un-finished assignment. The
        per-story pipeline spawns one teammate per /xp-assign invocation."""
        self._arm(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "First",
                        "in-progress",
                        execution_mode="teammate",
                        branch_name=BRANCH_001,
                    ),
                    _s(
                        "story-002",
                        "Second",
                        "in-progress",
                        execution_mode="teammate",
                        branch_name=BRANCH_002,
                    ),
                ]
            )
        )
        with self._spawned("story-001"):
            self._assert_blocks(_lead_write())


class TestAssignGateIsStateDerived(_AssignGateTestCase):
    """The bug: a marker whose story moved on kept blocking (concern
    ad536b4d1ef3). Note the concern's stated root cause is FALSE —
    xp-assign/scripts/preload.sh ends in an unconditional `rm -f`, so running
    /xp-assign always cleared it. The marker went STALE, not unclearable."""

    def test_stale_marker_does_not_block(self):
        """Marker armed, but its story was accepted — nothing to assign."""
        self._arm(SPRINT_ALL_ACCEPTED)
        with self._spawned():
            self._assert_allows(_lead_write())

    def test_stale_marker_does_not_resurrect_when_a_story_is_scheduled(self):
        """The difference between inert and self-clearing.

        A suppress-only fix (quiet at 0-scheduled + 0-in-progress) leaves the
        marker on disk, so the next scheduled story springs the gate back —
        demanding /xp-assign for a plan review from days earlier. Scheduling is
        /xp-schedule's business; there is still nothing to ASSIGN.
        """
        self._arm(SPRINT_SCHEDULED_AFTER_STALE)
        with self._spawned():
            self._assert_allows(_lead_write())

    def test_stale_marker_is_deleted_not_merely_skipped(self):
        """Self-clearing means the marker LEAVES DISK, not that it is ignored.

        This is the whole distinction. A skipped-but-present marker is a loaded
        gun: it fires again the instant state happens to satisfy the predicate.
        Deleting it is what makes resurrection impossible rather than unlikely.
        """
        self._arm(SPRINT_ALL_ACCEPTED)
        with self._spawned():
            self._assert_allows(_lead_write())
        self.assertFalse(
            (self.smm_dir / ".assign-pending").exists(),
            "a moot marker must be consumed, not left on disk to resurrect",
        )

    def test_promoting_a_teammate_frontier_cannot_resurrect_a_stale_marker(self):
        """The resurrection the `scheduled`-only test misses.

        A stale marker + a story merely SCHEDULED is quiet on the predicate
        alone. But /xp-schedule PROMOTES that story to in-progress/teammate, and
        an un-spawned in-progress teammate story is precisely what the predicate
        says the gate is FOR. A marker still on disk would fire there — telling
        the lead to /xp-assign a story whose plan review has not happened,
        inverting plan->review->spawn. The consume is what prevents it: by the
        time the frontier is promoted, the marker is already gone.
        """
        self._arm(SPRINT_ALL_ACCEPTED)
        with self._spawned():
            self._assert_allows(_lead_write())  # consumes the moot marker

        # /xp-schedule now promotes the next teammate frontier. Pre-plan-review.
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "First", "done", execution_mode="teammate"),
                    _s(
                        "story-002",
                        "Second",
                        "in-progress",
                        execution_mode="teammate",
                        branch_name=BRANCH_002,
                    ),
                ]
            )
        )
        with self._spawned():  # story-002 un-spawned: the predicate alone says BLOCK
            self._assert_allows(_lead_write())

    def test_solo_story_does_not_arm_the_gate(self):
        """A solo story spawns no teammate, so /xp-assign has no spawn target."""
        self._arm(SPRINT_SOLO_IN_PROGRESS)
        with self._spawned():
            self._assert_allows(_lead_write())

    def test_no_sprint_does_not_block(self):
        """No sprint at all — the marker cannot possibly be actionable."""
        self._arm()
        with self._spawned():
            self._assert_allows(_lead_write())

    def test_no_marker_no_block(self):
        """The predicate alone must NOT gate: a teammate story sits in-progress
        and un-spawned for the whole window between /xp-schedule and the plan
        review, and blocking there would forbid planning it."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned():
            self._assert_allows(_lead_write())


class TestAssignGateExemptions(_AssignGateTestCase):
    """Who the gate does not apply to. Unchanged by the state-derived fix."""

    def test_plan_file_exempt_from_assign_gate(self):
        """Writing the plan itself is how the lead gets TO /xp-assign."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        plan_input = _lead_write(
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan\n1. Do stuff",
            },
        )
        with self._spawned():
            result = pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-assign", result)

    def test_teammate_worktree_exempt_from_assign_gate(self):
        """A teammate can clear none of these gates: it never plans, it is
        dispatched BY /xp-assign, and headless it has no user to ask."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with self._spawned():
            result = pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-assign", result)

    def test_a_teammate_never_consumes_the_leads_marker(self):
        """The exemption is settled BEFORE the predicate, so a teammate returns
        without ever reaching the consume. It must: the marker is the LEAD's
        gate, living in the SHARED SMM dir, and a teammate writing code while
        its own story is spawned would otherwise silently disarm the lead's
        pending assignment for the NEXT story."""
        self._arm(
            _sprint_json(
                [
                    _s(
                        "story-010",
                        "Mine",
                        "in-progress",
                        execution_mode="teammate",
                        branch_name="dev/story-010-mine",
                    ),
                ]
            )
        )
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with self._spawned(
            "story-010", branches={"story-010": "dev/story-010-mine"}
        ):  # predicate WOULD say "nothing to assign"
            pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        self.assertTrue(
            (self.smm_dir / ".assign-pending").exists(),
            "a teammate must not consume the lead's marker",
        )

    def test_in_place_teammate_exempt_without_smm_dir_env(self):
        """The in-place teammate is identified via its marker under smm_dir.

        Passing smm_dir explicitly is load-bearing: the env leg falls back to
        $SMM_DIR, so a hook process running without that var would fail closed
        and over-gate a real teammate as the lead.
        """
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-010")
        in_place_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/src",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with (
            patch.dict(
                os.environ, {"XP_TEAMMATE_NAME": "worktree-story-010"}, clear=False
            ),
            self._spawned(),
        ):
            os.environ.pop("SMM_DIR", None)
            result = pre_tool_write.run(in_place_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-assign", result)


class TestLeadGateHotPath(_AssignGateTestCase):
    """run() fires on EVERY Write/Edit/MultiEdit, so the lead-only gate block
    must not pay for work the common case does not consume."""

    def test_no_armed_gate_skips_the_teammate_probe_entirely(self):
        """Common case -- lead, nothing armed -- must not probe at all.

        The probe parses cwd, reads the environment and can stat an in-place
        marker. Ordering it before the marker stat taxes every write in the
        overwhelmingly common no-marker case for an answer nothing consumes.
        """
        with patch.object(
            lead_gates.identity, "is_worktree_teammate", return_value=False
        ) as probe:
            pre_tool_write.run(_lead_write(), smm_dir=self.smm_dir)
        probe.assert_not_called()

    def test_no_armed_gate_never_scans_the_filesystem_for_worktrees(self):
        """`active_when` runs `git worktree list`. It must be reached only
        AFTER the marker stat passes, or every write in the project pays a
        subprocess for a gate that is not even armed."""
        with self._spawned() as lookup:
            pre_tool_write.run(_lead_write(), smm_dir=self.smm_dir)
        lookup.assert_not_called()

    def test_a_teammate_never_pays_for_the_worktree_scan(self):
        """Teammates are exempt from every lead gate, so the exemption must be
        settled BEFORE the predicate runs. Teammates write constantly, and the
        marker is routinely armed while they do (the lead plans story N+1 while
        they execute story N) — a probe-after-predicate order would tax every
        one of those writes with a git subprocess for a foregone answer."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with self._spawned() as lookup:
            pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        lookup.assert_not_called()

    def test_teammate_probe_runs_at_most_once_when_gates_armed(self):
        """Every lead-only gate shares one exemption, so one probe answers all.

        With all three markers armed, a per-gate probe would re-parse cwd and
        re-stat the in-place marker once per gate.
        """
        (self.smm_dir / ".plan-awaiting-review").write_text("p")
        (self.smm_dir / ".assign-pending").write_text("a")
        (self.smm_dir / ".question-gate").write_text("q")
        teammate_input = _make_write_input(
            session_id="t",
            cwd="/Users/dev/proj/.claude/worktrees/worktree-story-010",
            tool_input={"file_path": "/Users/dev/proj/src/app.py", "content": "x"},
        )
        with patch.object(
            lead_gates.identity, "is_worktree_teammate", return_value=True
        ) as probe:
            pre_tool_write.run(teammate_input, smm_dir=self.smm_dir)
        self.assertEqual(probe.call_count, 1)

    def test_probe_receives_smm_dir_so_it_never_depends_on_the_env(self):
        """The probe's env leg falls back to $SMM_DIR and fails CLOSED without
        it. run() already holds a validated smm_dir, so it must hand it over --
        otherwise a hook process with no SMM_DIR in env mistakes a live in-place
        teammate for the lead and over-gates it."""
        (self.smm_dir / ".assign-pending").write_text("a")
        with patch.object(
            lead_gates.identity, "is_worktree_teammate", return_value=True
        ) as probe:
            pre_tool_write.run(_lead_write(), smm_dir=self.smm_dir)
        self.assertEqual(probe.call_args.args[1], self.smm_dir)


class TestLeadGateTable(unittest.TestCase):
    """The table is the single home for lead gates — never a hand-rolled if."""

    def test_every_gate_is_declared_in_the_table(self):
        """A gate added as a 4th `if` in run() would inherit neither the
        teammate exemption nor the hot-path ordering. Both defaults are the
        opposite of what a hand-rolled gate gets by accident, and that is how
        the plan gate came to forbid the parallel pipeline for months.
        """
        markers_in_table = {gate.marker.name for gate in lead_gates._LEAD_GATES}
        self.assertEqual(
            markers_in_table,
            {".plan-awaiting-review", ".assign-pending", ".question-gate"},
        )

    def test_only_the_assign_gate_is_state_derived_today(self):
        """`active_when` is opt-in per gate. The plan and question gates are
        cleared by the act they demand (a plan review, a user's answer), so
        they have no state to derive from — leaving them predicate-free keeps
        them off the filesystem scan.
        """
        stateful = {
            gate.marker.name
            for gate in lead_gates._LEAD_GATES
            if gate.active_when is not None
        }
        self.assertEqual(stateful, {".assign-pending"})


if __name__ == "__main__":
    unittest.main()
