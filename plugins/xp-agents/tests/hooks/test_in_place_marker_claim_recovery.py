#!/usr/bin/env python3
"""Tests for the in-place marker's GUARDED REWRITE, the door mutex's failure
rules, the manual recovery hatch, and the real-process respawn-after-kill AC.

Split from test_in_place_marker_claim.py at the 500-line ceiling. Claim
exclusivity (including the concurrent-claimant property) and the LOCK-based
adjudication leg are in test_in_place_marker_claim_exclusivity.py.

Shared story (see that file's docstring too): story-006 guarded the two DELETE
doors (the reap, and the supervisor's finally); this story guards the WRITE
door the same disaster could re-arm through. The GUARDED REWRITE
(rewrite_own_in_place_marker, tested here) narrows the case the claim cannot
reach: the marker being replaced under a live supervisor after it was cleared
out-of-band (an operator rm'ing a "stuck" marker, then a respawn claiming it).
It makes every write on the path ownership-CHECKED — not ownership-atomic: the
check reads an inode and the rename that follows replaces the path, so a
respawn landing inside that window is still clobbered. See
rewrite_own_in_place_marker for why that residue is left open.

Also covers each door's rule when the door mutex is UNAVAILABLE (the claim
must refuse; the teardown must still release the name), the manual recovery
hatch for a genuinely wedged name (and the hazard it trades for), and the
documented kill-then-respawn recovery flow driven through real processes.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import in_place_locks
import in_place_marker
import worktree
from _in_place_marker_claim_helpers import _ClaimTestCase
from conftest import (
    dead_pid,
    held_door_mutex,
    live_in_place_holder,
    live_pid,
    reap,
)


class TestGuardedRewrite(_ClaimTestCase):
    """The second write on the marker (the child's pid, recorded at on_spawn).

    It takes NO lock — the supervisor already holds one for the whole episode —
    and it is gated on HOLDING the name rather than on the marker's content. That
    gate is what stops the old disaster: an unconditional rewrite let a supervisor
    overwrite a marker it did not own and thereby FORGE the content-proof of
    ownership its own teardown then checked, deleting a live teammate's marker. A
    hold cannot be forged.
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


class TestTheRecoveryHatch(_ClaimTestCase):
    """How a human frees a name that is genuinely wedged — and the exact price.

    A wedge is possible (a RECYCLED child pid reads LIVE and refuses its name
    forever), so there has to be a way out. It is deliberately a human one:
    nothing in the tree globs `*.lock`, and nothing should start.

    The story this was planned from asserted that rm'ing the holder lock frees a
    LIVE name. It does NOT, and the difference is load-bearing — so it is pinned
    here rather than left as prose. With the lock file gone, the name falls back
    to the LEGACY pid adjudication, which still refuses while the marker's pids
    read alive. The lock and the marker COVER EACH OTHER; both must go.

    Two things follow, and both are things a future change could quietly undo:
      - `_legacy_verdict` is NOT a migration shim to delete once pre-lock markers
        age out. It is the second leg of this coupling. test 2 below fails if it
        is deleted.
      - a `*.lock` sweep — a plausible "tidy the SMM dir" chore — would take the
        lock leg away and hand out live names. test 3 says what that costs.
    """

    def test_rm_ing_the_holder_lock_alone_does_NOT_free_a_live_name(self):
        """The correction. The marker's pids still speak for the name."""
        with live_in_place_holder(self.smm_dir, self.name) as holder:
            in_place_locks.holder_lock_path(self.smm_dir, self.name).unlink()

            with self.assertRaises(in_place_marker.InPlaceNameHeld):
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertTrue(holder.proc.poll() is None, "the holder is still alive")

    def test_and_it_is_the_legacy_pid_fallback_that_refuses_it(self):
        """Names the mechanism, so deleting it breaks a test rather than a user.

        With no lock file, the ONLY thing that knows the name is taken is the
        marker's supervisor pid, read by the legacy fallback's PID adjudication.

        Asserting merely "it raises" would NOT pin that: an unparseable marker
        raises too (unadjudicable is never treated as free), so a `_legacy_verdict`
        gutted to answer a blanket UNPROVEN for every lockless marker would keep
        this green while quietly ceasing to read pids at all. The refusal MESSAGE
        is what tells the two legs apart, so that is what is asserted — once for
        each leg.
        """
        with live_in_place_holder(self.smm_dir, self.name):
            in_place_locks.holder_lock_path(self.smm_dir, self.name).unlink()

            # The PID leg: live pids in the marker ⇒ refused as LIVE.
            with self.assertRaises(in_place_marker.InPlaceNameHeld) as live_refusal:
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
            self.assertIn("a live in-place teammate", str(live_refusal.exception))

            # The UNPROVEN leg: same missing lock, but nothing left to read pids
            # from ⇒ still refused, and the message says so in the other voice.
            self.marker.write_text("worktree-story-001")
            with self.assertRaises(in_place_marker.InPlaceNameHeld) as unproven:
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
            self.assertIn("neither live nor provably dead", str(unproven.exception))

    def test_rm_ing_BOTH_frees_a_live_name_which_is_the_hatch_and_the_hazard(self):
        """The hatch, and the hazard, are the same act — so it is pinned, not
        hidden. Removing both files lets a claimant take a name a LIVE teammate is
        still running under: two `claude` processes in one checkout. That is the
        cost of having any way out at all, and it is why this takes a human and
        why no automated sweep may ever do it.
        """
        with live_in_place_holder(self.smm_dir, self.name) as holder:
            in_place_locks.holder_lock_path(self.smm_dir, self.name).unlink()
            self.marker.unlink()

            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

            self.assertEqual(self.marker.read_text().split(), [str(os.getpid())])
            self.assertTrue(
                holder.proc.poll() is None,
                "...while the original teammate is STILL RUNNING — this is the "
                "two-claudes state, reachable only by a human removing both files",
            )


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
