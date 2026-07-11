#!/usr/bin/env python3
"""Tests for worktree.py marker helpers — story assignment path and
in-place teammate env lookup.

Covers: story_assignment_path, in_place_teammate_from_env,
has_live_in_place_teammate (pid-liveness probe).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree


def _dead_pid() -> int:
    """Spawn and reap a child process, returning its now-dead pid.

    Reaping via wait() removes the process table entry, so os.kill(pid, 0)
    reliably raises ProcessLookupError afterward — no PID-reuse race within
    a single test's timeframe.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


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
        marker.write_text(str(_dead_pid()))
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


if __name__ == "__main__":
    unittest.main()
