#!/usr/bin/env python3
"""Tests for the in-place marker REAP and its identity guard.

The reap is the one path that DELETES a marker, so it is the one path that can
demote a live teammate to the lead. It carries its own hazard (read → probe →
unlink is not atomic) and its own contract (fail OPEN on anything unadjudicable,
reap only what is PROVEN dead), which is why it lives apart from the marker
path/env-lookup tests in test_worktree_markers.py.

Covers: has_live_in_place_teammate's reap side effect, and the inode-identity
guard that keeps it from deleting a same-name respawn's LIVE marker.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

# The reap and its pid probe are private to in_place_marker and NOT among the
# six names worktree re-exports, so the race tests below must reach them here.
# Patching `worktree._probe_pid` would silently do nothing — `_marker_pid_alive`
# resolves the name from its OWN module namespace.
import in_place_marker
import worktree
from conftest import dead_pid, live_pid


class TestDeadMarkerReap(unittest.TestCase):
    """The probe reaps markers it proves dead, so leaks cannot accumulate
    until a recycled pid reads live again and re-suppresses the gate.

    Reaping is surgical: only a definitively-dead pid (ProcessLookupError) is
    unlinked. A marker we merely cannot adjudicate — unreadable, or holding a
    legacy name written by a still-running older spawn_teammate — is left
    alone, because deleting a LIVE teammate's marker would demote it to lead
    and lose its commit attribution.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _marker(self, name: str) -> Path:
        return worktree.in_place_marker_path(self.smm_dir, name)

    def test_dead_pid_marker_is_reaped(self):
        """A proven-dead marker is unlinked, not merely reported dead."""
        path = self._marker("worktree-story-001")
        path.write_text(str(dead_pid()))
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(path.exists(), "dead marker should have been reaped")

    def test_live_marker_is_not_reaped(self):
        """A live teammate's marker survives the probe."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-002")
        path = self._marker("worktree-story-002")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(path.exists(), "live marker must never be reaped")

    def test_legacy_name_marker_is_not_reaped(self):
        """A legacy name-content marker may belong to a LIVE teammate running
        the older spawn_teammate — unadjudicable, so leave it on disk."""
        path = self._marker("worktree-story-003")
        path.write_text("worktree-story-003")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(path.exists(), "unadjudicable marker must not be reaped")

    def test_non_utf8_marker_reads_dead_instead_of_crashing_the_gate(self):
        """Fail OPEN on undecodable bytes — the direction is the whole point.

        The reap used to read via `path.read_text()`, guarded only by
        `except OSError`. UnicodeDecodeError is a ValueError, so a marker whose
        bytes are not valid UTF-8 escaped that clause and took the Stop hook down
        with it — and a gate that CRASHES never fires, which silently certifies a
        half-written tree. Reading bytes and decoding inside the `except ValueError`
        clause routes it to the same verdict as any other unparseable marker:
        reads dead (the gate fires), and is NOT reaped (it is unadjudicable — the
        bytes could belong to a live teammate).
        """
        path = self._marker("worktree-story-006")
        path.write_bytes(b"\xff\xfe not utf-8")

        self.assertFalse(
            worktree.has_live_in_place_teammate(self.smm_dir),
            "an undecodable marker must read DEAD, not raise — a crashed gate "
            "never fires",
        )
        self.assertTrue(path.exists(), "unadjudicable marker must not be reaped")

    def test_symlinked_marker_reads_dead_and_is_not_followed(self):
        """A symlinked marker is refused (O_NOFOLLOW), not followed.

        `read_text()` FOLLOWS symlinks, so a symlink planted at a marker path
        would be read through to its target — and if that target held a LIVE pid,
        the probe read LIVE and SUPPRESSED the accept gate. That is the wrong
        failure direction (a suppressed gate certifies a half-written tree; a
        spurious one merely nags), and the writer already refuses to write through
        a symlink, so a symlinked marker is never something we wrote.

        Opening with O_NOFOLLOW makes it unreadable ⇒ dead, in line with every
        other marker we cannot adjudicate. Neither the link nor its target is
        unlinked: we never proved anything about that file's pids.
        """
        target = self.smm_dir / "elsewhere"
        target.write_text(str(live_pid()))  # a LIVE pid behind the link
        link = self._marker("worktree-story-007")
        link.symlink_to(target)

        self.assertFalse(
            worktree.has_live_in_place_teammate(self.smm_dir),
            "a symlinked marker must not be followed to a live pid — following "
            "it lets a file we never wrote suppress the accept gate",
        )
        self.assertTrue(link.is_symlink(), "unadjudicable marker must not be reaped")
        self.assertTrue(
            target.exists(), "the reap must not follow through to the target"
        )

    def test_dead_marker_reaped_while_live_one_survives(self):
        """A mixed dir reaps only the dead marker and still reports live."""
        dead = self._marker("worktree-story-004")
        dead.write_text(str(dead_pid()))
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-005")
        live = self._marker("worktree-story-005")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(dead.exists())
        self.assertTrue(live.exists())

    def test_dead_marker_is_reaped_even_when_a_live_marker_is_seen_first(self):
        """The reap is a SIDE EFFECT of the per-marker probe, so it must not
        hang on `any()`'s short-circuit: the first live marker would stop the
        scan and every dead marker behind it would survive. Which markers get
        reaped would then depend on glob order — i.e. on the filesystem.

        Sibling `test_dead_marker_reaped_while_live_one_survives` cannot catch
        this: it creates the dead marker FIRST, so scandir order happens to
        probe it before the live one. Here the live marker is created first, so
        a short-circuiting scan skips the dead one and leaks it — which is the
        accumulation the reap exists to prevent (a recycled pid later reads
        live and re-suppresses the gate).
        """
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        live = self._marker("worktree-story-001")
        dead = self._marker("worktree-story-002")
        dead.write_text(str(dead_pid()))

        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

        self.assertTrue(live.exists(), "live marker must never be reaped")
        self.assertFalse(
            dead.exists(),
            "dead marker must be reaped regardless of the order glob yields it",
        )


class TestReapIdentityGuard(unittest.TestCase):
    """The reap is read → probe → unlink, and `unlink` targets the PATH, not the
    inode whose pids were proven dead. Between the read and the unlink sits an
    unbounded gap (N os.kill syscalls plus file I/O), and the reap runs on every
    Stop where the accept gate would otherwise fire.

    Kill-then-respawn is the documented recovery for a stuck teammate, so a fresh
    same-name marker landing inside that gap is a routine event, not an exotic
    one. Unlinking then deletes the LIVE teammate's marker — and all three
    existence-only consumers (identity, pre_tool_skill, commit_handling) flip to
    "not a teammate": the teammate is demoted to lead and its commits are
    misattributed.

    The guard: unlink only if the file on disk is STILL the inode that was read.
    It attaches to the unlink alone — never to the return value, so the fail-open
    contract (unreadable ⇒ reads dead ⇒ the gate fires) is untouched. Skipping a
    reap is always safe: a leaked marker reads dead and suppresses nothing.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

    def _respawn_on_first_probe(self):
        """Simulate a same-name respawn landing between the read and the unlink.

        Returns a _probe_pid side effect that, on its FIRST call, writes a fresh
        marker through the PRODUCTION writer, then reports the pid it was asked
        about as proven dead — driving the caller straight into the unlink with a
        different file now sitting at the path.

        The fresh marker MUST go through write_in_place_marker (atomic
        mkstemp+rename ⇒ a NEW inode), not path.write_text (truncate in place ⇒
        the SAME inode). With write_text the identity would rest on st_mtime_ns
        alone: the rewrite lands microseconds after the first write, which
        macOS/APFS resolves but Linux's coarse 1-4ms mtime clock does NOT — both
        writes would stamp the same tick, the guard would compare EQUAL, and this
        test would delete the live marker and fail on CI while passing here.
        """
        calls = []

        def side_effect(pid: int) -> bool:
            if not calls:
                calls.append(pid)
                worktree.write_in_place_marker(self.smm_dir, self.name)
            return False  # proven dead — authorizes the reap

        return side_effect

    def test_marker_written_during_the_probe_survives_the_reap(self):
        """The headline race: the respawn's marker is NOT deleted."""
        self.marker.write_text(str(dead_pid()))

        with patch.object(
            in_place_marker, "_probe_pid", side_effect=self._respawn_on_first_probe()
        ):
            worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertTrue(
            self.marker.exists(),
            "a marker rewritten between the read and the unlink is NOT the one "
            "whose pids were proven dead — it must survive the reap",
        )

    def test_the_respawned_teammate_is_not_demoted_to_lead(self):
        """...and the consequence that actually bites: the live teammate keeps
        its identity, so it stays gated as a teammate and its commits are still
        attributed to it."""
        self.marker.write_text(str(dead_pid()))

        with patch.object(
            in_place_marker, "_probe_pid", side_effect=self._respawn_on_first_probe()
        ):
            worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertTrue(
            worktree.in_place_teammate_from_env(self.smm_dir, self.name),
            "deleting the live marker demotes the teammate to the lead",
        )

    def test_the_surviving_marker_reads_live_on_the_next_stop(self):
        """The guard suppresses the unlink, not the return: THIS probe still
        reads dead (fail-open — the gate fires), and the fresh marker's live pids
        are simply re-probed on the next Stop, where they read live. Nothing is
        lost by declining to reap."""
        self.marker.write_text(str(dead_pid()))

        with patch.object(
            in_place_marker, "_probe_pid", side_effect=self._respawn_on_first_probe()
        ):
            during = worktree.has_live_in_place_teammate(self.smm_dir)

        self.assertFalse(
            during,
            "the pids READ were proven dead, so this call must still read dead — "
            "the guard gates the unlink, never the return",
        )
        self.assertTrue(
            worktree.has_live_in_place_teammate(self.smm_dir),
            "the next Stop re-probes the fresh marker and finds it live",
        )

    def test_stat_failure_blocks_the_unlink_and_still_reads_dead(self):
        """Both directions of the fail-safe, in one test. If the identity cannot
        be re-established at unlink time, we cannot prove the file is the one we
        proved dead — so we do NOT unlink (a leak is harmless) — and we still
        return dead, so the accept gate fires (a suppressed gate is not)."""
        self.marker.write_text(str(dead_pid()))

        with patch.object(in_place_marker.os, "lstat", side_effect=OSError("boom")):
            alive = in_place_marker._marker_pid_alive(self.marker)

        self.assertFalse(alive, "a proven-dead marker must still read dead")
        self.assertTrue(
            self.marker.exists(),
            "cannot prove the file is still ours ⇒ must not unlink it",
        )

    def test_rewriting_the_marker_changes_the_inode(self):
        """Pins the coupling the guard is built on.

        The identity check is only a valid "unchanged since I read it" predicate
        while write_in_place_marker remains atomic (mkstemp + rename ⇒ a new
        inode every write). Nothing else in the suite pins that. If a future
        change makes the writer mutate the file in place, st_ino stops changing,
        the guard compares EQUAL against a respawn's marker, and the race quietly
        reopens with every other test still green. Break loudly here instead.
        """
        worktree.write_in_place_marker(self.smm_dir, self.name)
        first = self.marker.stat().st_ino

        worktree.write_in_place_marker(self.smm_dir, self.name, 424242)

        self.assertNotEqual(
            first,
            self.marker.stat().st_ino,
            "write_in_place_marker must stay atomic (new inode per write) — the "
            "reap guard's identity check is disarmed the moment it writes in place",
        )


if __name__ == "__main__":
    unittest.main()
