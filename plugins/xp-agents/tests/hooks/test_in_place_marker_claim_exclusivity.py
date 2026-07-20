#!/usr/bin/env python3
"""Tests for the in-place marker CLAIM — exclusivity and adjudication.

Split from test_in_place_marker_claim.py at the 500-line ceiling. Covers claim
exclusivity (including against a CONCURRENT claimant — the property the door
mutex + holder lock buy over a check-then-write), the marker-is-not-the-name
residual (rm'ing a marker does not free a live name), and the LOCK-based
adjudication leg (a recycled pid must not outvote a free lock; a free lock must
not outvote a live child).

The guarded rewrite, the door mutex's failure rules, the manual recovery
hatch, and the real-process respawn-after-kill AC are in
test_in_place_marker_claim_recovery.py.

Shared story (see that file's docstring too): story-006 guarded the two DELETE
doors (the reap, and the supervisor's finally). Both prove ownership before
unlinking. But a marker WRITE was still unconditional — an atomic rename over
whatever sat at the path — and that re-armed the identical failure through a
third door, because a supervisor could *re-establish* the very ownership the
delete guards check, simply by overwriting:

    A claims [A] -> B publishes [B, B_child] -> A's on_spawn CLOBBERS to [A, A_child]
    -> A's finally reads tokens[0] == A -> ownership PASSES -> UNLINK

A deletes live teammate B's marker. B is demoted to the lead: skill gating drops
and its commits are misattributed. The content proof is not sufficient on its own
precisely because a writer can forge it against itself.

The claim (claim_in_place_marker, tested here) makes taking the name exclusive.
A name a LIVE teammate holds cannot be taken at all — two live teammates under
one name is the state we never want — so B can never appear under a live A in
the first place.

Note which BRANCH a fixture exercises. A marker written by hand has no holder
lock beside it, so it is adjudicated by the LEGACY pid fallback; only a claim
made by a real process (live_in_place_holder / dead_in_place_holder) exercises
the lock. Both branches are load-bearing and both are covered below.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import in_place_locks
import in_place_marker
import worktree
from _in_place_marker_claim_helpers import _ClaimTestCase
from conftest import (
    _SCRIPTS_DIR,
    _SMM_DIR,
    CHILD_WAIT_TIMEOUT_S,
    dead_in_place_holder,
    dead_pid,
    live_in_place_holder,
    live_pid,
    reap,
)


class TestClaimIsExclusive(_ClaimTestCase):
    """The claim is what makes the name exclusive.

    It runs under the door mutex, and it ADJUDICATES the name exactly as the reap
    does rather than blindly refusing or blindly clobbering what it finds:

      - holder reads LIVE  -> refuse. Two live teammates under one name is the
        state we never want, and clobbering is what demotes one of them.
      - holder is PROVEN dead -> take the holder lock, reap the stale marker, and
        publish. This is the kill-then-respawn recovery flow, and it MUST work.
      - holder is unadjudicable -> refuse loudly. It is not proof of death, so
        deleting it could delete a live teammate's marker; blocking the spawn
        with a clear error is recoverable (inspect and rm), corrupting a live
        teammate's identity is not.

    The tests that write a marker by hand exercise the LEGACY leg of that
    adjudication (no lock file beside the marker). TestClaimAdjudicatesByLock
    below covers the leg that answers for every marker written since.
    """

    def test_a_claim_on_a_free_name_publishes_our_pid(self):
        """The baseline: an unheld name is claimed, and the marker names us."""
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertEqual(self.marker.read_text().split(), [str(os.getpid())])
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_claiming_a_name_a_live_teammate_holds_is_refused(self):
        """The first write door. A's opening marker write used to be an
        unconditional rename, so spawning A while B was LIVE simply clobbered B's
        marker — and A's finally then deleted it (the content now named A),
        demoting B. Refusing the claim is the only correct answer."""
        with live_pid() as b_child:
            self.marker.write_text(f"{dead_pid()} {b_child}")

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

    def test_a_refused_claim_leaves_the_live_holders_marker_byte_intact(self):
        """Refusing is not enough on its own — the refusal must not have
        clobbered the holder on the way out (a half-published claim would be the
        same bug wearing a different hat)."""
        with live_pid() as b_child:
            content = f"{dead_pid()} {b_child}"
            self.marker.write_text(content)

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertEqual(self.marker.read_text(), content)
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_a_leaked_all_dead_marker_does_not_block_a_respawn(self):
        """Kill-then-respawn is the DOCUMENTED recovery flow, and this is the
        constraint that kills a naive always-exclusive claim.

        A SIGKILLed supervisor skips its finally, so it leaks its marker —
        routinely. If the claim refused on any existing marker, that leak would
        permanently block every same-name respawn and the recovery flow would be
        dead. The claim adjudicates instead: all pids PROVEN dead ⇒ reap it and
        take the path.
        """
        self.marker.write_text(f"{dead_pid()} {dead_pid()}")

        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertEqual(
            self.marker.read_text().split(),
            [str(os.getpid())],
            "a respawn must be able to take a name whose every pid is dead",
        )

    def test_an_unadjudicable_marker_refuses_the_claim(self):
        """A legacy name-content marker may belong to a LIVE teammate running
        older code. It is not proof of death, so the reap will not collect it and
        the claim must not clobber it. Fail loud (and recoverable: rm it) rather
        than silently demote a teammate we cannot see."""
        self.marker.write_text("worktree-story-001")

        with self.assertRaises(in_place_marker.InPlaceNameHeld):
            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertTrue(self.marker.exists(), "an unadjudicable marker is not ours")

    def test_a_publish_that_dies_mid_flight_leaves_NO_MARKER_AND_NO_HELD_NAME(self):
        """A claim that fails after taking the lock must give the name BACK.

        The lock is taken before the marker is published (that ordering is what
        makes "marker present, lock absent" mean "pre-lock artifact"). So a
        publish that raises — ENOSPC, EACCES — leaves this process HOLDING a name
        with no marker to index it. That state is invisible to the reap (the
        marker is the index: no marker, no lock is ever probed) and would refuse
        every respawn of the name for as long as this process lives. Undoing the
        hold on the way out is what stops a failed spawn from wedging a name.

        write_text_atomic renames last, so nothing lands at the path either.
        """
        with (
            patch.object(in_place_marker, "write_text_atomic", side_effect=OSError()),
            self.assertRaises(OSError),
        ):
            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertFalse(self.marker.exists(), "a failed publish left a marker")
        self.assertFalse(
            in_place_locks.holds_name(self.smm_dir, self.name),
            "a failed claim kept the name held — with no marker to index it, "
            "nothing can ever reap it and every respawn is refused",
        )
        # And the proof that matters: the name is genuinely re-claimable.
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
        self.assertEqual(self.marker.read_text().split(), [str(os.getpid())])

    def test_a_completed_claim_leaks_no_temp_file(self):
        """The happy path cleans up its temp file too (write_text_atomic stages
        into the SMM dir and renames; a leaked stage file would litter it)."""
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertEqual(list(self.smm_dir.glob("*.tmp")), [])
        self.assertTrue(self.marker.read_text().strip())

    def test_exactly_one_of_many_concurrent_claimants_wins(self):
        """The property the mutex + holder lock buy, and the ONLY test here that
        can catch its loss.

        Every other test in this class passes just as well against a
        check-then-write (`if not path.exists(): write_text_atomic(...)`) — the
        shape a future simplifier would naturally reach for, and exactly the bug:
        two supervisors both read "free", both write, and the second silently owns
        a name the first is already running under. Two live teammates under one
        name is the state this whole module exists to prevent. Adjudicate-then-
        publish is safe only because the door mutex makes the pair ATOMIC against
        another claimant, and only racing real processes at it can assert that —
        the failure mode is a lost race, not a wrong answer, so no serial caller
        can observe the difference.

        Each claimant HOLDS the name after winning (sleeps), because that is what a
        real supervisor does — it lives for the whole episode. A claimant that won
        and exited instantly would be a DEAD episode, and the others reaping its
        marker and re-claiming would be the kill-then-respawn recovery path working
        correctly, not an exclusivity violation. Getting that wrong turns this into
        a test of the reap wearing an exclusivity costume.

        Real subprocesses, not threads: the GIL serialises enough of a Python-level
        check-then-write to hide the race, so threads would let the broken shape
        pass.
        """
        claimants = 24
        hold_s = 2  # >> the losers' claim attempts, << CHILD_WAIT_TIMEOUT_S
        # The claimants spin to a shared wall-clock start so they hit the publish
        # TOGETHER. Without the barrier they arrive spread over process-startup
        # jitter (~tens of ms) — far wider than the check-then-write window they
        # exist to catch — and the broken shape slips through most runs. The
        # barrier is what makes this test a reliable detector rather than a
        # lottery ticket.
        start_at = time.time() + 1.0
        script = (
            "import os, sys, time\n"
            f"sys.path[:0] = {[str(_SCRIPTS_DIR), str(_SMM_DIR)]!r}\n"
            "from pathlib import Path\n"
            "import in_place_marker\n"
            f"while time.time() < {start_at!r}:\n"
            "    pass\n"
            "try:\n"
            "    in_place_marker.claim_in_place_marker("
            f"Path({str(self.smm_dir)!r}), {self.name!r})\n"
            "except in_place_marker.InPlaceNameHeld:\n"
            "    print('LOST', flush=True)\n"
            "    sys.exit(0)\n"
            "print('WON', os.getpid(), flush=True)\n"
            f"time.sleep({hold_s})\n"  # hold the name, as a live supervisor does
        )
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
            )
            for _ in range(claimants)
        ]
        try:
            outcomes = [
                p.communicate(timeout=CHILD_WAIT_TIMEOUT_S)[0].split() for p in procs
            ]
        finally:
            for p in procs:
                if p.poll() is None:
                    reap(p)

        winners = [o for o in outcomes if o and o[0] == "WON"]
        self.assertEqual(
            len(winners),
            1,
            f"{len(winners)} of {claimants} concurrent claimants took a name a LIVE "
            f"claimant already held — taking it is not atomic: {outcomes}",
        )
        # The losers must also have left the winner's marker alone: a claimant that
        # clobbers or reaps on its way out is the original bug, just racing.
        self.assertEqual(self.marker.read_text().split(), [winners[0][1]])
        self.assertEqual(
            list(self.smm_dir.glob("*.tmp")), [], "a losing claimant leaked its temp"
        )


class TestTheMarkerIsNotTheName(_ClaimTestCase):
    """rm'ing a marker does not give its name away.

    This is the residual the old design could not close. The marker was the ONLY
    record of the name, so an operator rm'ing a "stuck" marker — the documented
    way to unwedge a name, and therefore a routine act — handed a LIVE teammate's
    name to the next claimant: two `claude` processes in one checkout, and
    whichever tore down first deleted the other's marker.

    The name now lives in the LOCK, which the operator has not touched, so it
    survives its marker being deleted.

    Closed for the CLAIM only, and the difference is worth stating: because the
    marker is also the INDEX (no marker ⇒ no lock is ever probed), rm'ing a live
    teammate's marker still BLINDS the Stop gate. The name stays refused; the
    accept gate simply goes quiet. That is not a regression — today's glob does
    the same — but it is not closed either.
    """

    def test_rm_ing_the_marker_does_not_free_a_live_name(self):
        with live_in_place_holder(self.smm_dir, self.name):
            self.marker.unlink()  # the operator "unsticks" a live teammate

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

    def test_and_the_claim_that_was_refused_published_nothing(self):
        """A refusal that left a marker behind would be the bug wearing a hat: the
        live holder's name would now index a marker naming the REFUSED claimant."""
        with live_in_place_holder(self.smm_dir, self.name):
            self.marker.unlink()

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertFalse(self.marker.exists())
            self.assertFalse(in_place_locks.holds_name(self.smm_dir, self.name))

    def test_control_the_same_name_is_free_once_the_holder_dies(self):
        """Positive control: the refusal above tracks the holder's LIFE, not the
        mere existence of a lock file. Same fixture, same missing marker — but the
        holder is dead, so the name is claimable and the recovery flow still
        works."""
        dead_in_place_holder(self.smm_dir, self.name)
        self.marker.unlink()

        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertEqual(self.marker.read_text().split(), [str(os.getpid())])


class TestClaimAdjudicatesByLock(_ClaimTestCase):
    """The claim door's LOCK leg — the one every marker written since this story
    lands on, and the one no hand-written fixture can reach.

    Every other claim test above writes marker bytes with no lock beside them, so
    it is answered by the LEGACY fallback. These use real holder processes, which
    is the only way to put a lock in the picture at all.
    """

    def test_a_live_holders_name_cannot_be_claimed(self):
        """The headline refusal, through the lock rather than through a pid: a
        name whose holder lock is HELD is not available, full stop. Two `claude`
        processes in one checkout is the state the claim exists to prevent."""
        with live_in_place_holder(self.smm_dir, self.name):
            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertTrue(self.marker.exists(), "a refused claim spares the marker")
            self.assertFalse(in_place_locks.holds_name(self.smm_dir, self.name))

    def test_a_free_lock_beats_a_live_pid_in_the_marker(self):
        """The wedge this story removes, at the CLAIM door.

        The reap has the mirror of this (a live pid + a free lock still reads
        dead); without it here, the claim would still be adjudicating the
        SUPERVISOR by pid — and a leaked marker whose supervisor pid got RECYCLED
        to some unrelated live process would refuse every respawn of that name,
        forever, with no recovery but a manual rm.
        """
        dead_in_place_holder(self.smm_dir, self.name)
        with live_pid() as recycled:
            # A live pid in the supervisor slot, a dead one in the child's — and a
            # holder lock nobody holds.
            self.marker.write_text(f"{recycled} {dead_pid()}")

            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertEqual(
                self.marker.read_text().split(),
                [str(os.getpid())],
                "a FREE holder lock proves the supervisor gone; a live pid in the "
                "marker is a recycled pid and must not outvote it",
            )

    def test_a_free_lock_does_not_beat_a_live_child(self):
        """...but the OR-leg still holds the door. The supervisor is a tee: SIGKILL
        it and its `claude` child runs on, reparented, still writing the tree. The
        lock is free and says DEAD; the child says LIVE; LIVE wins, or the claim
        admits a SECOND `claude` into the checkout the first is working in."""
        with live_in_place_holder(self.smm_dir, self.name, with_child=True) as holder:
            holder.sigkill()  # lock released by the kernel; child still alive

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertTrue(self.marker.exists(), "the live child keeps its marker")


if __name__ == "__main__":
    unittest.main()
