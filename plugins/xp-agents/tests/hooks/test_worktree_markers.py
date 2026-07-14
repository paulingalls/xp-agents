#!/usr/bin/env python3
"""Tests for worktree.py marker helpers — story assignment path and
in-place teammate env lookup.

Covers: story_assignment_path, in_place_teammate_from_env,
has_live_in_place_teammate (pid-liveness probe), and the supervisor/child
lifetime the marker's pid list exists to span.

The REAP — the one path that deletes a marker, and the inode-identity guard that
keeps it from deleting a live respawn's — lives in test_in_place_marker_reap.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from conftest import dead_pid, live_pid, release_in_place_holds


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
            worktree.claim_in_place_marker(smm_dir, "worktree-story-001")
            result = worktree.in_place_teammate_from_env(smm_dir, "worktree-story-001")
            # The claim holds a REAL lock; give it back before the dir goes.
            release_in_place_holds(smm_dir)
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
    """has_live_in_place_teammate answers name-free — the sensor the accept gate
    consumes when it doesn't know which teammate (if any) is executing in place.

    Liveness is the holder LOCK now (see test_in_place_marker_reap.py, which owns
    that contract). What survives HERE is the pid machinery it still rests on: the
    LEGACY fallback, which adjudicates a pre-lock marker by its pids exactly as
    before. Every marker below is written WITHOUT a claim, so it has no lock file
    beside it — which is precisely what makes it legacy.

    The pid guards are unchanged and still load-bearing: the same _probe_pid also
    answers the child-pid OR-leg, where a mis-read pid would reap a live
    teammate's marker.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _legacy_marker(self, content: str, name: str = "worktree-story-001") -> Path:
        """A pre-lock marker: pid content, and NO holder lock beside it."""
        marker = worktree.in_place_marker_path(self.smm_dir, name)
        marker.write_text(content)
        return marker

    def test_live_pid_marker_for_any_name_is_true(self):
        """Name-free: a live legacy marker under ANY teammate name reports True."""
        with live_pid() as pid:
            self._legacy_marker(str(pid), name="worktree-story-042")
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_dead_pid_marker_is_false(self):
        """The leak case: a SIGKILLed spawn_teammate's marker outlives the
        process it named. Liveness must not let it defer forever."""
        self._legacy_marker(str(dead_pid()))
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_pid_zero_marker_is_false(self):
        """os.kill(0, 0) signals the caller's own process group and
        succeeds — a naive liveness check would treat pid 0 as alive
        forever. The pid<=0 guard exists specifically to kill this trap."""
        self._legacy_marker("0")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_legacy_name_content_marker_is_false(self):
        """A marker written before the pid change contains a teammate NAME, not
        a pid. Unparseable as an int -> treated as dead, so the gate fires rather
        than staying silently suppressed."""
        self._legacy_marker("worktree-story-001")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_unreadable_marker_is_false(self):
        """Fail-open on an unreadable marker: the read raises OSError, which
        must read as DEAD so the gate FIRES. An unreadable marker that read as
        live would silently suppress a legitimate accept gate forever."""
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.mkdir()  # a directory opens fine, but reading it is EISDIR
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_negative_pid_marker_is_false(self):
        """os.kill accepts negative pids as PROCESS GROUP targets, so a
        negative pid must not reach the probe either — the guard is pid<=0,
        not pid==0."""
        self._legacy_marker("-1")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_oversized_pid_marker_is_false(self):
        """int() is arbitrary-precision but os.kill needs a C int, so a huge
        value raises OverflowError — an ArithmeticError, which escapes BOTH
        except clauses and crashes the Stop hook.

        This is the one branch that failed in the WRONG direction: the probe
        promises to fail OPEN (unreadable => dead => the gate fires), but a
        crash means the gate never fires at all.
        """
        self._legacy_marker(str(10**30))
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
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-001")
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-002")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_own_in_place_marker(self.smm_dir, "worktree-story-001")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_own_in_place_marker(self.smm_dir, "worktree-story-002")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_write_then_remove_lifecycle(self):
        worktree.claim_in_place_marker(self.smm_dir, "worktree-story-007")
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
        worktree.remove_own_in_place_marker(self.smm_dir, "worktree-story-007")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))


class TestOrphanedTeammateMarker(unittest.TestCase):
    """The supervising `spawn_teammate` is a TEE, not the teammate.

    It launches the real teammate — the `claude` child — with a plain
    `subprocess.Popen` (no `start_new_session`), then holds the child's stdout
    pipe and waits. A SIGTERM/SIGKILL delivered to the SUPERVISOR's pid alone
    does NOT propagate to that child: the child is reparented to init and keeps
    running. Empirically, a child in a silent stretch — a long model call, which
    the watchdog tolerates for 900s — survives its supervisor indefinitely. Only
    a *chatty* child dies promptly, on BrokenPipe at its next stdout write.

    A marker holding ONLY the supervisor's pid therefore reads DEAD while a live
    teammate is still writing the tree, and BOTH consumers break:

      - `has_live_in_place_teammate` -> False -> the accept gate fires
        mid-flight and `/xp-accept` certifies a half-written tree — the very
        defect this sprint exists to fix, through a different door.
      - the probe REAPS the marker -> `in_place_marker_exists` -> False -> the
        live teammate is demoted to the lead: it loses `xp-*` skill gating and
        its commits are misattributed.

    The marker records EVERY process whose life means the in-place episode is
    still in flight. Alive if ANY is alive; reaped only once ALL are proven
    dead — the one condition under which no consumer can be harmed. That is
    what lets the two consumers pull in opposite directions safely: existence
    outlives the supervisor (so a live teammate keeps its identity), while
    liveness still goes false once nothing is left running (so a dead teammate
    cannot suppress the gate, and leaks cannot accumulate).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # A claim keeps its holder lock for the life of the PROCESS. Right for a
        # supervisor (it exits); an fd leak in a test worker (it does not).
        self.addCleanup(release_in_place_holds, self.smm_dir)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

    def test_orphaned_live_child_reads_live_though_supervisor_is_dead(self):
        """The headline case: supervisor SIGKILLed, teammate still running."""
        with live_pid() as child:
            self.marker.write_text(f"{dead_pid()} {child}")
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_orphaned_live_child_keeps_its_marker(self):
        """...and the marker survives, so the live teammate keeps its identity
        (skill gating + commit attribution) rather than being demoted to lead."""
        with live_pid() as child:
            self.marker.write_text(f"{dead_pid()} {child}")
            worktree.has_live_in_place_teammate(self.smm_dir)
            self.assertTrue(self.marker.exists())
            self.assertTrue(
                worktree.in_place_teammate_from_env(self.smm_dir, self.name)
            )

    def test_supervisor_alive_child_dead_reads_live(self):
        """The post-exit bookkeeping window: the child has exited but the
        supervisor is still promoting the story. Still in flight — defer."""
        with live_pid() as supervisor:
            self.marker.write_text(f"{supervisor} {dead_pid()}")
            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(self.marker.exists())

    def test_all_recorded_pids_dead_reads_dead_and_reaps(self):
        """Only when EVERY recorded process is proven dead is the episode over
        — and only then may the marker be reaped."""
        self.marker.write_text(f"{dead_pid()} {dead_pid()}")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(self.marker.exists(), "fully-dead marker must be reaped")

    def test_supervisor_only_marker_is_still_live_before_the_child_spawns(self):
        """The marker is written BEFORE the child exists (so the child's first
        hook can never lose the identity race). In that window the supervisor's
        pid is the whole truth, and a one-pid marker must still read live."""
        worktree.claim_in_place_marker(self.smm_dir, self.name)
        self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))

    def test_unadjudicable_pid_alongside_dead_one_is_not_reaped(self):
        """A pid we cannot adjudicate (here: too large for a C int, which
        os.kill raises OverflowError on) is not PROOF of death. Mixed with a
        proven-dead pid it still blocks the reap — never delete a marker we
        cannot prove is finished."""
        self.marker.write_text(f"{dead_pid()} {10**30}")
        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertTrue(self.marker.exists(), "unadjudicable pid must block the reap")


if __name__ == "__main__":
    unittest.main()
