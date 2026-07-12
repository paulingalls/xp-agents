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
  - the GUARDED REWRITE (rewrite_own_in_place_marker) covers the case the claim
    cannot: the marker being replaced under a live A after it was cleared
    out-of-band (an operator rm'ing a "stuck" marker, then a respawn claiming
    it). It makes EVERY write on the path ownership-checked, so the invariant is
    total: the path is only ever created from nothing, or mutated by its creator.

Covers: claim exclusivity, the kill-then-respawn recovery path (a leaked all-dead
marker must NOT permanently block a respawn), and the guarded rewrite.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import in_place_marker
import worktree
from conftest import dead_pid, live_pid, reap


class TestClaimIsExclusive(unittest.TestCase):
    """The claim is what makes the name exclusive.

    A marker is published by linking a fully-written temp file into the path,
    which fails if the path is taken. On collision the claim ADJUDICATES the
    holder rather than blindly refusing or blindly clobbering:

      - holder reads LIVE  -> refuse. Two live teammates under one name is the
        state we never want, and clobbering is what demotes one of them.
      - holder is PROVEN dead -> reap it (the guarded reap) and take the path.
        This is the kill-then-respawn recovery flow, and it MUST keep working.
      - holder is unadjudicable -> refuse loudly. It is not proof of death, so
        deleting it could delete a live teammate's marker; blocking the spawn
        with a clear error is recoverable (inspect and rm), corrupting a live
        teammate's identity is not.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

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

    def test_a_publish_that_dies_mid_flight_leaves_NOTHING_at_the_path(self):
        """Why the claim LINKS a fully-written file into place rather than
        O_EXCL-creating the path and then writing to it.

        An O_EXCL create takes the path FIRST and fills it second, so it publishes
        a ZERO-BYTE marker for the width of that write. A supervisor dying in that
        window (ENOSPC, SIGKILL) leaks an EMPTY marker — and an empty marker reads
        "not alive" but is NOT proof of death, so the reap never collects it (see
        _marker_pid_alive) and the claim above refuses on it. It would block every
        same-name respawn FOREVER, which is precisely the permanent block that
        kill-then-respawn must never hit.

        Link-after-write inverts that: the content exists before the name does, so
        a death anywhere before the link leaves the path untouched. Asserting the
        happy-path marker is non-empty would NOT pin this — it stays true under
        the O_EXCL design too. Killing the publish mid-flight is what discriminates
        them.
        """
        with (
            patch.object(in_place_marker.os, "link", side_effect=OSError("crash")),
            self.assertRaises(OSError),
        ):
            in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertFalse(
            self.marker.exists(),
            "a publish that died before the link left a marker at the path — an "
            "empty one is never reaped and blocks every respawn forever",
        )
        self.assertEqual(
            list(self.smm_dir.glob("*.tmp")), [], "the claim leaked its temp file"
        )

    def test_a_completed_claim_leaks_no_temp_file(self):
        """The happy path cleans up its temp file too (it is only ever a staging
        area — the link is what publishes it)."""
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)

        self.assertEqual(list(self.smm_dir.glob("*.tmp")), [])
        self.assertTrue(self.marker.read_text().strip())


class TestGuardedRewrite(unittest.TestCase):
    """The second write on the marker (the child's pid, recorded at on_spawn) is
    a rewrite, and it must prove ownership exactly as the deletes do.

    The claim already stops a respawn appearing under a LIVE supervisor. This
    covers the case it cannot: the marker being cleared out-of-band (an operator
    rm'ing a "stuck" marker) and re-claimed by a respawn while the old supervisor
    is still running. Without the guard the old supervisor's on_spawn overwrites
    the respawn's marker with its own pids — re-forging the ownership its finally
    then checks, and deleting a live teammate's marker.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

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
        """Pins the coupling the REAP's identity guard rests on: every write on
        this path lands a new inode, so a respawn's marker can never compare
        equal to the one the reap proved dead. Break loudly if a future change
        makes the rewrite mutate in place."""
        in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
        first = self.marker.stat().st_ino

        in_place_marker.rewrite_own_in_place_marker(self.smm_dir, self.name, 424242)

        self.assertNotEqual(first, self.marker.stat().st_ino)


class TestClaimRespawnAfterKill(unittest.TestCase):
    """AC: the documented recovery flow, with REAL processes rather than
    hand-written pids — a claim that only ever works against synthetic markers
    would not prove the recovery path comes up."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

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
