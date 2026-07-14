#!/usr/bin/env python3
"""Capstone: sprint_stop_gate.py stays quiet for a LIVE in-place teammate.

story-001 proved the pid-liveness probe and its consumption in
`_deferred` at the unit level (calling `_deferred` / `has_live_in_place_teammate`
in-process). This capstone proves the same claim end-to-end: real subprocess
invocation of `sprint_stop_gate.py` over a real fixture SMM, real marker files
on disk, and real `os.kill(pid, 0)` liveness probes — no mocks, no
monkeypatching anywhere in this file.

Every "quiet" assertion is paired with a positive control that is identical
except for the marker, so a fixture that is quiet for the wrong reason (e.g.
the accept gate never firing at all) cannot masquerade as proof.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import worktree
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_REVIEWING_ONLY,
    _IntegrationTestCase,
    _make_stop_input,
    dead_pid,
    live_pid,
)

_MARKER_NAME = "worktree-story-999"


class TestStopGateInPlace(_IntegrationTestCase):
    """`sprint_stop_gate.py` deference to a live in-place teammate marker."""

    def _checkout_story_branch(self, branch: str) -> None:
        """Check out a fresh branch off main and commit one file, so
        `commits_ahead(base) == 1` — a real, measured "has work" signal
        rather than the cannot-measure short-circuit.

        The class git repo is shared across tests (`_bases.py`), and
        `setUp` resets the worktree/index but NOT the checked-out branch.
        So the restore is registered BEFORE the repo is mutated: a
        `make_commit` that fails partway (branch created, commit not)
        would otherwise leave the cleanup unregistered and leak the branch
        into every sibling test in the class.
        """
        self.addCleanup(self._restore_main, branch)
        _bf.make_commit(str(self.tmpdir), branch, "story_file.txt", "wip\n", "wip")

    def _restore_main(self, branch: str) -> None:
        """Put the class-shared repo back on `main` and drop the story branch.

        Fails LOUD (`check=True`) rather than swallowing git errors: a
        silently-failed restore corrupts every subsequent test in the class,
        which is exactly the failure a quiet cleanup would hide.
        """
        _bf.checkout_main(str(self.tmpdir))
        if _bf.branch_exists(str(self.tmpdir), branch):
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=self.tmpdir,
                capture_output=True,
                check=True,
            )

    def _run_gate(self, cwd: str | None = None) -> subprocess.CompletedProcess:
        overrides = {"cwd": cwd} if cwd is not None else {}
        return self._run_script("sprint_stop_gate.py", _make_stop_input(**overrides))

    def _assert_quiet(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def _assert_accept_fired(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("/xp-accept", parsed["reason"])
        self.assertNotIn("/xp-sprint-review", parsed["reason"])

    # -- Group A: production input shape (cwd present, real commits-ahead) --

    def test_live_marker_silences_accept_gate_with_cwd(self):
        self._checkout_story_branch("story-live-marker")
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").touch()
        worktree.claim_in_place_marker(self.smm_dir, _MARKER_NAME)

        result = self._run_gate(cwd=str(self.tmpdir))

        self._assert_quiet(result)

    def test_no_marker_emits_accept_message_with_cwd(self):
        """Positive control for the test above: identical fixture minus the
        marker. Proves the gate fires by real commits-ahead measurement, not
        by an unrelated fixture quirk."""
        self._checkout_story_branch("story-no-marker")
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").touch()

        result = self._run_gate(cwd=str(self.tmpdir))

        self._assert_accept_fired(result)

    def test_dead_pid_marker_emits_accept_message_with_cwd(self):
        """A leaked marker (supervising process dead) cannot silence the gate."""
        self._checkout_story_branch("story-dead-marker")
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").touch()
        worktree.claim_in_place_marker(self.smm_dir, _MARKER_NAME)
        marker = worktree.in_place_marker_path(self.smm_dir, _MARKER_NAME)
        marker.write_text(str(dead_pid()))

        result = self._run_gate(cwd=str(self.tmpdir))

        self._assert_accept_fired(result)

    def test_dead_pid_marker_is_reaped_by_the_hook(self):
        """The dead-pid marker is deleted as a side effect of gate evaluation.

        Builds its own fixture and fires its own subprocess (self-contained,
        per the no-inter-test-dependency rule) and asserts BOTH that the gate
        fired (the reap is a side effect of `_deferred`, which only runs when
        the gate is evaluated) and that the marker file is gone -- otherwise
        this would pass vacuously if the gate never ran.
        """
        self._checkout_story_branch("story-reap")
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").touch()
        worktree.claim_in_place_marker(self.smm_dir, _MARKER_NAME)
        marker = worktree.in_place_marker_path(self.smm_dir, _MARKER_NAME)
        marker.write_text(str(dead_pid()))

        result = self._run_gate(cwd=str(self.tmpdir))

        self._assert_accept_fired(result)
        self.assertFalse(marker.exists())

    # -- Group B: sole-variable proof (no cwd needed) --

    def test_live_marker_silences_unconditional_accept_message(self):
        """SPRINT_REVIEWING_ONLY fires the accept message unconditionally
        (no `.accept` marker, no commits-ahead check needed) — so the
        in-place marker is provably the SOLE variable that silences it."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        worktree.claim_in_place_marker(self.smm_dir, _MARKER_NAME)

        result = self._run_gate()

        self._assert_quiet(result)

    def test_no_marker_emits_unconditional_accept_message(self):
        """Positive control: identical fixture minus the marker fires."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)

        result = self._run_gate()

        self._assert_accept_fired(result)

    # -- Group C: the ORPHANED teammate (supervisor dead, teammate alive) --
    #
    # spawn_teammate is only a TEE around the real teammate: it launches the
    # `claude` child with a plain Popen (no start_new_session), holds its stdout
    # pipe, and waits. A SIGTERM/SIGKILL delivered to spawn_teammate's pid does
    # NOT propagate to that child — it is reparented to init and keeps running.
    # A child mid-silent-stretch (a long model call; the watchdog tolerates 900s
    # of them) survives its supervisor indefinitely; only a chatty child dies
    # promptly, on BrokenPipe at its next write.
    #
    # This is the routine leak path the reap exists for, so it is exactly where
    # the gate must NOT go blind. The two tests below differ in ONE byte-level
    # respect — whether the recorded child pid is alive — and nothing else.

    def test_orphaned_live_teammate_still_silences_accept_gate(self):
        """Supervisor SIGKILLed, teammate still writing the tree: the gate must
        stay quiet, and the live teammate must KEEP its marker (else it is
        demoted to the lead and its commits are misattributed)."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        marker = worktree.in_place_marker_path(self.smm_dir, _MARKER_NAME)
        with live_pid() as teammate:
            marker.write_text(f"{dead_pid()} {teammate}")

            result = self._run_gate()

            self._assert_quiet(result)
            self.assertTrue(marker.exists(), "a live teammate must keep its marker")

    def test_control_orphaned_dead_teammate_fires_accept_gate(self):
        """Positive control for the test above: identical fixture, identical
        dead supervisor — the ONLY delta is that the recorded child is dead too.

        Without this control, "stays quiet for an orphan" could pass for the
        wrong reason: a probe that read live on any two-pid marker (or never
        went false at all) would silence the gate forever and look identical.
        Here the gate must fire and the marker must be reaped.
        """
        (self.smm_dir / "sprint.json").write_text(SPRINT_REVIEWING_ONLY)
        marker = worktree.in_place_marker_path(self.smm_dir, _MARKER_NAME)
        marker.write_text(f"{dead_pid()} {dead_pid()}")

        result = self._run_gate()

        self._assert_accept_fired(result)
        self.assertFalse(marker.exists(), "fully-dead episode must be reaped")


if __name__ == "__main__":
    unittest.main()
