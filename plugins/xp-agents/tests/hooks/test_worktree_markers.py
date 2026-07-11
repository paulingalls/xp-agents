#!/usr/bin/env python3
"""Tests for worktree.py marker helpers — story assignment path and
in-place teammate env lookup.

Covers: story_assignment_path, in_place_teammate_from_env,
has_live_in_place_teammate (pid-liveness probe).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from conftest import dead_pid


class TestStoryAssignmentPath(unittest.TestCase):
    def test_returns_dotfile_in_smm_dir(self):
        """story_assignment_path returns {smm_dir}/.story-assignment-{name}."""
        result = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        self.assertEqual(result, Path("/smm/.story-assignment-teammate-step-1"))

    def test_different_names_produce_different_paths(self):
        result_a = worktree.story_assignment_path(Path("/smm"), "teammate-step-1")
        result_b = worktree.story_assignment_path(Path("/smm"), "teammate-step-2")
        self.assertNotEqual(result_a, result_b)


class TestInPlaceTeammateFromEnv(unittest.TestCase):
    """in_place_teammate_from_env returns True when env_name names a live
    in-place teammate (marker present), False otherwise.

    Wraps the env-name-not-None + in_place_marker_exists check that
    identity, pre_tool_skill, and commit_handling previously rolled by hand.
    Caller-side id-shape validation (is_teammate_agent_id) and smm_dir
    resolution stay at call sites; the helper centralizes the core guard.
    """

    def test_returns_true_when_marker_present_and_env_not_none(self):
        """When env_name is non-None and marker exists, returns True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            worktree.write_in_place_marker(smm_dir, "worktree-story-001")
            result = worktree.in_place_teammate_from_env(smm_dir, "worktree-story-001")
            self.assertTrue(result)

    def test_returns_false_when_env_name_is_none(self):
        """When env_name is None, returns False (no marker lookup)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            result = worktree.in_place_teammate_from_env(smm_dir, None)
            self.assertFalse(result)

    def test_returns_false_when_marker_absent(self):
        """When env_name is non-None but marker doesn't exist, returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            smm_dir = Path(tmpdir)
            result = worktree.in_place_teammate_from_env(smm_dir, "worktree-story-999")
            self.assertFalse(result)


class TestHasLiveInPlaceTeammate(unittest.TestCase):
    """has_live_in_place_teammate probes marker files for a LIVE pid,
    name-free — the sensor the accept-gate consumes when it doesn't know
    which teammate (if any) is executing in place.

    A marker leaked by a SIGKILLed spawn_teammate must read as dead, not
    linger forever — that's the whole point of the pid-liveness bound over
    a bare existence check.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_live_pid_marker_for_any_name_is_true(self):
        """Name-free: a live-pid marker under ANY teammate name reports True."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-042")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_dead_pid_marker_is_false(self):
        """The leak case: a SIGKILLed spawn_teammate's marker outlives the
        process it named. Liveness must not let it defer forever."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text(str(dead_pid()))
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_pid_zero_marker_is_false(self):
        """os.kill(0, 0) signals the caller's own process group and
        succeeds — a naive liveness check would treat pid 0 as alive
        forever. The pid<=0 guard exists specifically to kill this trap."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text("0")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_legacy_name_content_marker_is_false(self):
        """A marker written before this story's pid change contains a
        teammate NAME, not a pid. Unparseable as an int -> treated as
        dead, so the gate fires rather than staying silently suppressed."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text("worktree-story-001")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_unreadable_marker_is_false(self):
        """Fail-open on an unreadable marker: read_text raises OSError, which
        must read as DEAD so the gate FIRES. An unreadable marker that read as
        live would silently suppress a legitimate accept gate forever."""
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.mkdir()  # IsADirectoryError — an OSError from read_text
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_negative_pid_marker_is_false(self):
        """os.kill accepts negative pids as PROCESS GROUP targets, so a
        negative pid must not reach the probe either — the guard is pid<=0,
        not pid==0."""
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text("-1")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_oversized_pid_marker_is_false(self):
        """int() is arbitrary-precision but os.kill needs a C int, so a huge
        value raises OverflowError — an ArithmeticError, which escapes BOTH
        except clauses and crashes the Stop hook.

        This is the one branch that failed in the WRONG direction: the probe
        promises to fail OPEN (unreadable => dead => the gate fires), but a
        crash means the gate never fires at all.
        """
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text(str(10**30))
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_empty_dir_and_unrelated_files_are_false(self):
        (self.smm_dir / ".accept").write_text("done")
        (self.smm_dir / "events.jsonl").write_text("")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_missing_smm_dir_is_false(self):
        """Fail-open: a genuinely nonexistent directory (not merely an
        empty one) — Path.glob() yields nothing rather than raising, so
        no marker is ever found to evaluate."""
        missing = self.smm_dir / "does-not-exist" / "nested"
        self.assertFalse(worktree.has_live_in_place_teammate(missing))

    def test_two_live_markers_then_one_removed_still_true(self):
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-001")
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-002")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_in_place_marker(self.smm_dir, "worktree-story-001")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_in_place_marker(self.smm_dir, "worktree-story-002")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_write_then_remove_lifecycle(self):
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-007")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_in_place_marker(self.smm_dir, "worktree-story-007")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))


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

    def test_dead_marker_reaped_while_live_one_survives(self):
        """A mixed dir reaps only the dead marker and still reports live."""
        dead = self._marker("worktree-story-004")
        dead.write_text(str(dead_pid()))
        worktree.write_in_place_marker(self.smm_dir, "worktree-story-005")
        live = self._marker("worktree-story-005")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(dead.exists())
        self.assertTrue(live.exists())


if __name__ == "__main__":
    unittest.main()
