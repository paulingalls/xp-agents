#!/usr/bin/env python3
"""Tests for the in-place marker CLAIM and the guarded rewrite — the WRITE door.

Story-006 guarded the two DELETE doors (the reap, and the supervisor's finally).
Both prove ownership before unlinking. But a marker WRITE was still unconditional
— an atomic rename over whatever sat at the path — and that re-armed the identical
failure through a third door, because a supervisor could *re-establish* the very
ownership the delete guards check, simply by overwriting:

    A claims [A] -> B publishes [B, B_child] -> A's on_spawn CLOBBERS to [A, A_child]
    -> A's finally reads tokens[0] == A -> ownership PASSES -> UNLINK

A deletes live teammate B's marker. B is demoted to the lead: skill gating drops
and its commits are misattributed. The content proof is not sufficient on its own
precisely because a writer can forge it against itself.

The fix has two legs, and they close different doors:

  - the CLAIM (claim_in_place_marker) makes taking the name exclusive. A name a
    LIVE teammate holds cannot be taken at all — two live teammates under one
    name is the state we never want — so B can never appear under a live A in
    the first place.
  - the GUARDED REWRITE (rewrite_own_in_place_marker) narrows the case the claim
    cannot reach: the marker being replaced under a live A after it was cleared
    out-of-band (an operator rm'ing a "stuck" marker, then a respawn claiming
    it). It makes every write on the path ownership-CHECKED — not ownership-
    atomic: the check reads an inode and the rename that follows replaces the
    path, so a respawn landing inside that window is still clobbered. See
    rewrite_own_in_place_marker for why that residue is left open.

Covers: claim exclusivity (including against a CONCURRENT claimant — the property
the door mutex + holder lock buy over a check-then-write, and the one a future
refactor is most likely to lose), the kill-then-respawn recovery path (a leaked
all-dead marker must NOT permanently block a respawn), each door's rule when the
door mutex is UNAVAILABLE, and the guarded rewrite.

Note which BRANCH a fixture exercises. A marker written by hand has no holder lock
beside it, so it is adjudicated by the LEGACY pid fallback; only a claim made by a
real process (live_in_place_holder / dead_in_place_holder) exercises the lock.
Both branches are load-bearing and both are covered below.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import in_place_locks
import in_place_marker
import worktree
from conftest import (
    _SCRIPTS_DIR,
    _SMM_DIR,
    CHILD_WAIT_TIMEOUT_S,
    dead_in_place_holder,
    dead_pid,
    held_door_mutex,
    live_in_place_holder,
    live_pid,
    reap,
    release_in_place_holds,
)


class _ClaimTestCase(unittest.TestCase):
    """A temp SMM dir, the name under test, and its marker path.

    tearDown gives back any holder lock this process still holds. A claim keeps
    its lock for the LIFE OF THE PROCESS — which is right for a supervisor (it
    then exits) and wrong for a test worker (it runs thousands more tests), so
    without this every claiming test leaks an fd and leaves a flock held on a temp
    dir that is about to be deleted. Registered before the temp dir's own cleanup
    so it runs BEFORE it (addCleanup is LIFO): the release finds its lock files by
    globbing the dir, so it cannot run after the dir is gone.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(release_in_place_holds, self.smm_dir)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)


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


class TestGuardedRewrite(_ClaimTestCase):
    """The second write on the marker (the child's pid, recorded at on_spawn) is
    a rewrite, and it must prove ownership exactly as the deletes do.

    The claim already stops a respawn appearing under a LIVE supervisor. This
    covers the case it cannot: the marker being cleared out-of-band (an operator
    rm'ing a "stuck" marker) and re-claimed by a respawn while the old supervisor
    is still running. Without the guard the old supervisor's on_spawn overwrites
    the respawn's marker with its own pids — re-forging the ownership its finally
    then checks, and deleting a live teammate's marker.
    """

    def test_a_rewrite_of_our_own_marker_records_the_child(self):
        """The baseline the fix must not break: our own marker IS rewritten, so
        the child's pid is recorded and a live child keeps the episode alive."""
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        in_place_marker.rewrite_own_in_place_marker(self.smm_dir, self.name, 424242)

        self.assertEqual(self.marker.read_text().split(), [str(os.getpid()), "424242"])

    def test_a_rewrite_is_refused_when_the_marker_is_not_ours(self):
        """A marker naming a different supervisor is not ours to overwrite."""
        with live_pid() as b_child:
            content = f"{dead_pid()} {b_child}"
            self.marker.write_text(content)

            in_place_marker.rewrite_own_in_place_marker(self.smm_dir, self.name, 99999)

            self.assertEqual(
                self.marker.read_text(),
                content,
                "rewriting a foreign marker re-forges the ownership the finally "
                "checks, and deletes a live teammate's marker",
            )

    def test_the_rewrite_publishes_a_new_inode(self):
        """The rewrite REPLACES the path, it never mutates the file in place.

        It is the one door that takes no door mutex (it holds the name already),
        so it is the one write that can land while another process is reading the
        marker — a legacy-leg adjudication, an operator's `cat`. A rename makes
        that reader see the old bytes or the new ones, never a torn half. An
        in-place truncate+write would put a window between them where the marker
        is empty, which reads UNPROVEN and suppresses nothing.
        """
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
        first = self.marker.stat().st_ino

        in_place_marker.rewrite_own_in_place_marker(self.smm_dir, self.name, 424242)

        self.assertNotEqual(first, self.marker.stat().st_ino)


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


class TestTheDoorMutexCanFail(_ClaimTestCase):
    """Each door states its own rule for an unavailable mutex. The reap's rule is
    pinned in test_in_place_marker_reap; the other two are pinned here.

    They disagree deliberately, so each needs its own test: the reap must ANSWER
    ANYWAY (a Stop gate that crashes never fires), while the claim must REFUSE
    (two claimants both publishing is two `claude` processes in one checkout).
    """

    def test_the_claim_refuses_rather_than_publish_unadjudicated(self):
        """Without the mutex the claim cannot know the name is free, and a claim
        that fell through to publish anyway would be the whole bug: two supervisors
        adjudicating "free" at once, both publishing, one checkout, two teammates.
        Refusing is loud and recoverable; publishing is not."""
        with (
            held_door_mutex(self.smm_dir),
            self.assertRaises(in_place_marker.InPlaceNameHeld),
        ):
            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertFalse(self.marker.exists(), "a refused claim published nothing")
        self.assertFalse(
            in_place_locks.holds_name(self.smm_dir, self.name),
            "a refused claim must not keep the name held",
        )
        # And the refusal is transient: with the mutex free, the name is claimable.
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

    def test_the_teardown_releases_the_name_even_without_the_mutex(self):
        """The teardown's rule: give the NAME back, skip only the unlink.

        The lock is what refuses a respawn, so failing to release it would wedge
        the name for as long as this process lives. The marker it leaves behind is
        inert — its holder lock is free now, so the next Stop reaps it and the next
        claim adjudicates it dead. (Note the leaked marker names a LIVE pid: us.
        The lock overrules it, which is the whole point of the story.)
        """
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        with held_door_mutex(self.smm_dir):
            in_place_marker.remove_own_in_place_marker(self.smm_dir, self.name)

            self.assertFalse(
                in_place_locks.holds_name(self.smm_dir, self.name),
                "the hold outlived the teardown — every respawn of this name is "
                "refused until this process exits",
            )
            self.assertTrue(self.marker.exists(), "the unlink is the part we skip")

        self.assertFalse(
            worktree.has_live_in_place_teammate(self.smm_dir),
            "the leaked marker must read DEAD — it names our (live) pid, but its "
            "holder lock is free, and the lock is the verdict",
        )
        self.assertFalse(self.marker.exists(), "the next Stop reaps what we leaked")


class TestClaimRespawnAfterKill(_ClaimTestCase):
    """AC: the documented recovery flow, with REAL processes rather than
    hand-written pids — a claim that only ever works against synthetic markers
    would not prove the recovery path comes up."""

    def _sleeper(self) -> subprocess.Popen:
        """A real, live child, reaped on a BOUNDED wait at teardown. Every wait on
        a child in this suite is bounded — an unbounded one can wedge CI with no
        output, which has happened."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        self.addCleanup(reap, proc)
        return proc

    def test_respawn_comes_up_once_the_killed_episodes_processes_are_gone(self):
        """Supervisor SIGKILLed AND its child gone ⇒ the name is free again."""
        sup = self._sleeper()
        child = self._sleeper()
        self.marker.write_text(f"{sup.pid} {child.pid}")

        # A live episode holds the name: a respawn must NOT be able to take it.
        with self.assertRaises(in_place_marker.InPlaceNameHeld):
            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        reap(sup)
        reap(child)

        # Both dead: the leaked marker is reaped and the respawn comes up.
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
        self.assertEqual(self.marker.read_text().split(), [str(os.getpid())])

    def test_a_surviving_child_still_holds_the_name(self):
        """Killing only the supervisor is NOT enough — its child is the real
        teammate and is still writing the tree. Refusing here is correct: the
        operator must kill the child too."""
        sup = self._sleeper()
        with live_pid() as child:
            self.marker.write_text(f"{sup.pid} {child}")
            reap(sup)

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)


if __name__ == "__main__":
    unittest.main()
