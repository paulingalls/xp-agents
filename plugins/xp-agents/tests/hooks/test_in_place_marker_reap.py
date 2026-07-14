#!/usr/bin/env python3
"""Tests for the in-place marker REAP — the door that DELETES a marker.

Liveness is no longer a pid. It is a LOCK:

    alive(name) := the holder lock is held  OR  the recorded child pid is alive

The holder lock is taken LOCK_NB by the supervisor and held for the whole
episode, so the KERNEL releases it when that supervisor dies — however it dies.
That is the property no pid bookkeeping can offer: a pid can be recycled, and a
recycled pid reads LIVE forever, blocking every respawn of the name (the leak
this story exists to close). A lock cannot be recycled.

The OR-leg is not a hedge, it is load-bearing. spawn_teammate is only a TEE
around the real teammate: SIGKILLing it does NOT propagate to the `claude`
child, and SIGKILL is the ROUTINE cancel path for a backgrounded spawn. A
lock-ONLY verdict would therefore read DEAD while a live teammate is still
writing the tree — reaping its marker (demoting it to the lead), firing the
accept gate on a half-written tree, and letting a respawn admit a SECOND
`claude` into the same checkout.

Covers: the lock verdict, the OR-leg, the legacy (pre-lock) fallback that must
not wedge, and the door mutex's failure rule — the reap must still ANSWER when
the mutex is unavailable, and skip only the unlink.
"""

import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import marker_names
import worktree
from _bases import _AssertNotNoneMixin
from conftest import (
    CHILD_WAIT_TIMEOUT_S,
    dead_in_place_holder,
    dead_pid,
    held_door_mutex,
    live_in_place_holder,
    live_pid,
)


class _InPlaceTestCase(_AssertNotNoneMixin, unittest.TestCase):
    """A temp SMM dir, plus the three paths every test here reasons about."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

    def _holder_lock(self, name: str | None = None) -> Path:
        return self.smm_dir / marker_names.IN_PLACE_HOLDER.format(
            name=name or self.name
        )

    def _door_mutex(self) -> Path:
        return self.smm_dir / marker_names.IN_PLACE_DOOR_LOCK


class TestLivenessIsALock(_InPlaceTestCase):
    """The headline: the verdict comes from the lock, not from the pid."""

    def test_a_live_holder_reads_live_and_keeps_its_marker(self):
        """The baseline. A supervisor that is running holds its lock, so its
        marker reads LIVE — and a live teammate must never lose its marker (the
        three existence-only consumers would demote it to the lead)."""
        with live_in_place_holder(self.smm_dir, self.name):
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(self.marker.exists(), "a live marker must never be reaped")

    def test_a_sigkilled_holder_releases_its_lock_so_its_marker_is_reaped(self):
        """THE kernel property this story is built on.

        SIGKILL runs no `finally` — Python cannot even install a handler — so the
        supervisor leaks its marker. But it cannot leak its LOCK: the kernel
        closes its fds on death, which releases the flock. A verdict derived from
        the lock therefore goes DEAD the instant the process does, with no
        cooperation from the dying process and no pid to misread.

        This is the routine cancel path for a backgrounded spawn, not an exotic
        one, which is why the reap must handle it without a human.
        """
        with live_in_place_holder(self.smm_dir, self.name) as holder:
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            holder.sigkill()

            self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertFalse(self.marker.exists(), "the leaked marker must be reaped")

    def test_a_dead_holders_leaked_marker_reads_dead_and_is_reaped(self):
        """Same property through the other fixture: a supervisor that exits
        without teardown (os._exit — what SIGKILL does to it) leaks its marker."""
        dead_in_place_holder(self.smm_dir, self.name)
        self.assertTrue(self.marker.exists(), "the fixture must leak its marker")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(self.marker.exists())

    def test_a_marker_naming_a_live_pid_is_still_dead_when_the_lock_is_free(self):
        """The recorded SUPERVISOR pid is ADVISORY — the lock overrules it.

        This is residual (5) dying: a leaked marker whose supervisor pid was
        RECYCLED to some unrelated live process used to read LIVE forever, and no
        respawn of that name could ever come up again. Now the lock answers, and
        the lock cannot be recycled. Only the CHILD pid still speaks (the OR-leg
        below), because only the child can outlive the lock's holder.
        """
        dead_in_place_holder(self.smm_dir, self.name)
        with live_pid() as unrelated:
            # A live pid in the supervisor slot; a dead one in the child's.
            self.marker.write_text(f"{unrelated} {dead_pid()}")

            self.assertFalse(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "a live pid in the marker must not outvote a FREE holder lock — "
                "that pid was recycled, and believing it wedges the name forever",
            )
            self.assertFalse(self.marker.exists())

    def test_a_dead_holder_with_a_live_child_reads_LIVE_and_is_not_reaped(self):
        """The OR-leg, and the regression a lock-only design would have shipped.

        spawn_teammate is a TEE: a SIGKILL to it does not reach the `claude`
        child, which is reparented to init and keeps writing the tree (a child
        mid-model-call survives indefinitely; the watchdog tolerates 900s of
        silence). The lock says DEAD — correctly, its holder IS dead — and the
        child says LIVE. LIVE wins.
        """
        with live_in_place_holder(self.smm_dir, self.name, with_child=True) as holder:
            self.assertIsNotNone(holder.child_pid)
            holder.sigkill()

            self.assertTrue(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "the supervisor is dead but its `claude` child is still writing "
                "the tree — reaping here fires the accept gate on a half-written "
                "tree and demotes the live child to the lead",
            )
            self.assertTrue(self.marker.exists(), "a live child keeps its marker")

    def test_a_dead_holder_with_a_dead_child_reads_dead(self):
        """Positive control for the OR-leg: identical fixture, identical dead
        supervisor — the ONLY delta is that the child is dead too. Without this,
        "stays live for an orphan" could pass for the wrong reason (a probe that
        never goes false at all would look identical)."""
        with live_in_place_holder(self.smm_dir, self.name, with_child=True) as holder:
            child = self._assert_not_none(holder.child_pid)
            holder.sigkill()
            os.kill(child, signal.SIGKILL)
            _wait_for_death(self, child)

            self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertFalse(self.marker.exists(), "a fully-dead episode is reaped")

    def test_an_unadjudicable_child_pid_is_treated_as_live(self):
        """A child pid we cannot adjudicate (EPERM, another uid, a value os.kill
        cannot even accept) is NOT proof of death. Refusing to delete a marker we
        cannot prove dead is the only direction that cannot destroy a live
        teammate's state — so it reads LIVE and survives.

        The price is stated openly in the story: a RECYCLED child pid reads LIVE
        and refuses the name. That is rm-recoverable; deleting a live teammate's
        marker is not.
        """
        dead_in_place_holder(self.smm_dir, self.name)
        # 10**30 overflows the C int os.kill needs — unadjudicable, not dead.
        self.marker.write_text(f"{dead_pid()} {10**30}")

        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(self.marker.exists(), "never reap what we cannot prove dead")


def _wait_for_death(case: unittest.TestCase, pid: int) -> None:
    """Block until `pid` is gone, bounded. A killed GRANDchild is reaped by init,
    not by us, so it is briefly a live-but-dying process — asserting DEAD before
    that lands is a flake, not a failure."""
    deadline = time.time() + CHILD_WAIT_TIMEOUT_S
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    case.fail(f"pid {pid} never died")


class TestLegacyMarkersDoNotWedge(_InPlaceTestCase):
    """A marker written BEFORE this protocol has no holder lock beside it.

    If such a marker were merely "unadjudicable" and never reaped, residual (5)
    would go from rare to CERTAIN for every marker existing at upgrade time — a
    worse bug than the one being fixed, shipped to every user. So a lock-less
    marker falls back to the OLD pid adjudication verbatim: reaped only when
    every recorded pid is PROVEN dead.

    No migration, no sweep, no wedge. Legacy markers age out on the first respawn
    (which always creates the lock BEFORE publishing the marker), and the
    fallback becomes dead code naturally.
    """

    def test_a_legacy_all_dead_marker_is_still_reaped(self):
        """The migration case that MUST keep working: it is auto-reaped today."""
        self.marker.write_text(f"{dead_pid()} {dead_pid()}")
        self.assertFalse(self._holder_lock().exists(), "fixture must be lock-less")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(
            self.marker.exists(),
            "a pre-lock marker whose pids are all dead is reaped TODAY — leaving "
            "it would wedge that name forever for every existing user",
        )

    def test_a_legacy_marker_with_a_live_pid_is_not_reaped(self):
        """...and one naming a LIVE process is a teammate running the OLD code.
        It has no lock to hold; its pid is all we have. Believe it."""
        with live_pid() as still_running:
            self.marker.write_text(f"{still_running} {dead_pid()}")

            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(self.marker.exists())

    def test_a_legacy_unadjudicable_marker_reads_dead_and_survives(self):
        """Old behavior verbatim: not alive (so the gate FIRES — a suppressed gate
        certifies a half-written tree, a spurious one merely nags) but not PROVEN
        dead either, so it is not reaped."""
        self.marker.write_text("worktree-story-001")  # a name, not a pid

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(self.marker.exists())

    def test_a_legacy_marker_never_creates_a_holder_lock(self):
        """The existence test in front of the lock open, pinned.

        An unconditional `open(holder, O_CREAT)` would CREATE the missing lock
        file, acquire it (nobody holds it), read DEAD — and reap a legacy marker
        that may belong to a live old-code teammate. Test existence FIRST.
        """
        with live_pid() as still_running:
            self.marker.write_text(str(still_running))

            worktree.has_live_in_place_teammate(self.smm_dir)

            self.assertFalse(
                self._holder_lock().exists(),
                "the reap CREATED a holder lock for a legacy marker — with that "
                "lock free, the next pass reads DEAD and reaps a live teammate",
            )


class TestTheMarkerIsTheIndex(_InPlaceTestCase):
    """Glob markers FIRST; only then consult a lock. No marker ⇒ no lock is
    opened, created, or probed."""

    def test_missing_smm_dir_is_false(self):
        """Fail-open on a genuinely nonexistent directory. Path.glob() yields
        nothing rather than raising — whereas an O_CREAT in a missing dir would
        raise, which is why the glob must come first."""
        missing = self.smm_dir / "does-not-exist" / "nested"
        self.assertFalse(worktree.has_live_in_place_teammate(missing))

    def test_no_markers_opens_no_lock_at_all(self):
        """The common Stop: no in-place teammate, so the gate pays ZERO lock cost
        and leaves no lock files behind to accumulate."""
        (self.smm_dir / "events.jsonl").write_text("")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(self._door_mutex().exists(), "took the mutex for nothing")
        self.assertEqual(list(self.smm_dir.glob("*.lock")), [])

    def test_a_lock_file_is_never_globbed_as_a_marker(self):
        """Neither lock name may match the marker glob. If one did, the reap would
        probe a LOCK as if it were a marker — its content is unparseable, so it
        would read UNADJUDICABLE forever: a phantom teammate that no reap can ever
        collect, and that every claim on that name would refuse on."""
        with live_in_place_holder(self.smm_dir, self.name):
            self.assertTrue(self._holder_lock().exists(), "fixture: lock must exist")
            self.assertTrue(self._door_mutex().exists(), "fixture: mutex must exist")

            pattern = marker_names.IN_PLACE_ACTIVE.format(name="*")
            self.assertEqual(
                sorted(p.name for p in self.smm_dir.glob(pattern)),
                [self.marker.name],
                "a lock file was caught by the marker glob",
            )

    def test_a_reaped_name_leaves_its_lock_file_behind_inert(self):
        """The reap unlinks the MARKER, never the lock file — and that asymmetry
        is deliberate. Unlinking a lock file is how you free a name that is still
        held (the next claimant O_CREATs a NEW inode and takes it), so nothing
        automatic may ever do it. The orphaned lock file is inert: with no marker
        to index it, no door will ever open it again."""
        dead_in_place_holder(self.smm_dir, self.name)

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

        self.assertFalse(self.marker.exists(), "the marker is reaped")
        self.assertTrue(self._holder_lock().exists(), "the lock file is NOT")


class TestTheDoorMutexCanFail(_InPlaceTestCase):
    """Every door that takes the mutex needs a rule for not getting it. The reap's
    rule: ANSWER ANYWAY — compute liveness from the holder lock + child pid, and
    skip only the UNLINK.

    Never raise: a crashed Stop hook is a gate that never fires.
    Never blanket-False: False means "no live teammate", so the accept gate would
    fire on a LIVE teammate's half-written tree and /xp-accept would certify it.
    That is the exact defect the marker exists to prevent, reached through the
    lock's own failure path.
    """

    def test_a_live_teammate_still_reads_live_without_the_mutex(self):
        """The one that matters. Degrading to False here would certify a
        half-written tree."""
        with live_in_place_holder(self.smm_dir, self.name):
            with held_door_mutex(self.smm_dir):
                alive = worktree.has_live_in_place_teammate(self.smm_dir)

            self.assertTrue(
                alive,
                "the mutex was unavailable and the gate went blind to a LIVE "
                "teammate — /xp-accept would now certify a half-written tree",
            )
            self.assertTrue(self.marker.exists())

    def test_a_dead_teammate_still_reads_dead_without_the_mutex(self):
        """The answer is still computed — it is only the UNLINK that is skipped."""
        dead_in_place_holder(self.smm_dir, self.name)

        with held_door_mutex(self.smm_dir):
            alive = worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertFalse(alive, "the reap must ANSWER, not refuse, without the mutex")

    def test_nothing_is_reaped_without_the_mutex(self):
        """The unlink is the only thing that needs the mutex (it is what makes a
        transient holder-lock hold invisible to a claimant). Skipping it leaks a
        marker, which is inert — the next Stop collects it."""
        dead_in_place_holder(self.smm_dir, self.name)

        with held_door_mutex(self.smm_dir):
            worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertTrue(
            self.marker.exists(),
            "reaped a marker without the door mutex — a concurrent claimant "
            "cannot tell that transient hold from a live teammate's",
        )
        # ...and it is genuinely only deferred: the next Stop reaps it.
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(self.marker.exists())

    def test_a_legacy_marker_is_not_reaped_without_the_mutex_either(self):
        """The legacy fallback's unlink is under the same rule."""
        self.marker.write_text(f"{dead_pid()} {dead_pid()}")

        with held_door_mutex(self.smm_dir):
            alive = worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertFalse(alive)
        self.assertTrue(self.marker.exists())


class TestUnreadableMarkersFailOpen(_InPlaceTestCase):
    """Anything the reap cannot read reads DEAD (the gate FIRES) and is NOT
    reaped. The direction is the whole point: a suppressed gate silently certifies
    a half-written tree; a spurious one merely nags. A CRASHED gate never fires at
    all, which is worse than either."""

    def test_non_utf8_marker_reads_dead_instead_of_crashing_the_gate(self):
        """UnicodeDecodeError is a ValueError, not an OSError — it escaped the
        reap's `except OSError` and took the Stop hook down with it."""
        self.marker.write_bytes(b"\xff\xfe not utf-8")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(self.marker.exists())

    def test_symlinked_marker_reads_dead_and_is_not_followed(self):
        """`read_text()` FOLLOWS symlinks, so a symlink planted at a marker path
        would be read through to its target — and a LIVE pid behind it would
        SUPPRESS the accept gate. O_NOFOLLOW makes it unreadable ⇒ dead."""
        target = self.smm_dir / "elsewhere"
        with live_pid() as pid:
            target.write_text(str(pid))
            self.marker.symlink_to(target)

            self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(self.marker.is_symlink(), "not ours ⇒ not reaped")
            self.assertTrue(target.exists(), "the reap must not follow through")

    def test_unreadable_marker_is_false(self):
        """A directory at the marker path opens fine but reads EISDIR."""
        self.marker.mkdir()
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))


class TestManyMarkers(_InPlaceTestCase):
    """The reap is a SIDE EFFECT of the per-marker probe, so it must not hang on
    `any()`'s short-circuit: the first LIVE marker would stop the scan and every
    dead marker behind it would survive — and which ones got reaped would depend
    on the order the filesystem happened to yield."""

    def test_a_dead_marker_is_reaped_even_when_a_live_one_is_seen_first(self):
        live_name, dead_name = "worktree-story-001", "worktree-story-002"
        dead_marker = worktree.in_place_marker_path(self.smm_dir, dead_name)

        with live_in_place_holder(self.smm_dir, live_name):
            live_marker = worktree.in_place_marker_path(self.smm_dir, live_name)
            dead_in_place_holder(self.smm_dir, dead_name)

            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

            self.assertTrue(live_marker.exists(), "live marker must never be reaped")
            self.assertFalse(
                dead_marker.exists(),
                "the dead marker must be reaped whatever order the glob yields",
            )


if __name__ == "__main__":
    unittest.main()
