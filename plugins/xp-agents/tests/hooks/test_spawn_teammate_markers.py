#!/usr/bin/env python3
"""Tests for spawn_teammate.py's in-place marker lifecycle.

The marker is the identity signal for a solo/in-place teammate (whose cwd is
the main checkout and so carries no worktree path marker). spawn_teammate is
its only writer and its only owning deleter, so its lifecycle — written before
the spawn, re-written with the child's pid once Popen returns, removed in the
finally — lives here.

Split out of test_spawn_teammate.py when that file crossed the 500-line
ceiling; the build_command / promote / env-wiring tests stay there.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _AssertNotNoneMixin
from conftest import dead_pid, live_pid


class TestInPlaceMarker(unittest.TestCase):
    """spawn_teammate --in-place writes a lifetime-scoped in-place marker that
    commit_handling requires before trusting XP_TEAMMATE_NAME (debt 06ddcc2c8e4d).
    """

    def _run(self, name_arg, smm_dir, *, in_place):
        """Run main() with run_with_tee patched to capture marker presence
        DURING the child run. Returns (marker_present_during_run: bool)."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        seen = {}

        def capture_tee(cmd, *, cwd=None, env=None, stdin=None, name=None, **kw):
            # Check against the closed-over name (a str), not the callback's
            # name kwarg (typed str | None) — the marker is name-keyed.
            seen["during"] = worktree.in_place_marker_exists(smm_dir, name_arg)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        argv = [
            "--name",
            name_arg,
            "--smm-dir",
            str(smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if in_place:
            argv.append("--in-place")
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(argv)
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return seen.get("during", False)

    def test_in_place_marker_present_during_run_absent_after(self):
        """Marker is live while the in-place child runs, gone once it exits."""
        import tempfile

        import worktree

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            during = self._run("worktree-story-001", smm_dir, in_place=True)
            self.assertTrue(during, "marker must be present during the in-place run")
            self.assertFalse(
                worktree.in_place_marker_exists(smm_dir, "worktree-story-001"),
                "marker must be removed after the in-place run (lifetime-scoped)",
            )

    def test_worktree_mode_writes_no_in_place_marker(self):
        """A normal worktree spawn never writes the in-place marker."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            during = self._run("worktree-story-001", smm_dir, in_place=False)
            self.assertFalse(
                during, "worktree spawns must not write the in-place marker"
            )

    def test_in_place_marker_removed_when_child_run_fails(self):
        """The lifetime-scoped marker is removed by the finally even when the
        child run raises (watchdog SIGTERM/SIGKILL → run_with_tee raises
        CalledProcessError, rc!=0 recovery). Only a SIGKILL of spawn_teammate
        ITSELF leaks the marker — a normal child failure must not."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        with tempfile.TemporaryDirectory() as d:
            smm_dir = Path(d)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write("test prompt")
                prompt_path = f.name

            def boom(*a, **kw):
                raise subprocess.CalledProcessError(1, ["claude"])

            argv = [
                "--name",
                "worktree-story-001",
                "--smm-dir",
                str(smm_dir),
                "--prompt-file",
                prompt_path,
                "--in-place",
            ]
            try:
                with (
                    patch.object(
                        spawn_teammate, "create_worktree", return_value="/tmp/wt"
                    ),
                    patch.object(spawn_teammate, "run_with_tee", side_effect=boom),
                    self.assertRaises(subprocess.CalledProcessError),
                ):
                    spawn_teammate.main(argv)
            finally:
                Path(prompt_path).unlink(missing_ok=True)

            self.assertFalse(
                worktree.in_place_marker_exists(smm_dir, "worktree-story-001"),
                "marker must be removed even when the child run fails",
            )


class TestInPlaceMarkerRecordsChildPid(_AssertNotNoneMixin, unittest.TestCase):
    """spawn_teammate is a TEE around the real teammate (the `claude` child),
    and a signal to spawn_teammate's pid does NOT propagate to that child — it
    is reparented to init and keeps running. So the marker must record the
    CHILD's pid too, or the liveness probe reaps a live teammate's marker and
    un-suppresses the accept gate mid-flight.

    This is the wiring test: run_with_tee hands the child's pid back via
    on_spawn, and spawn_teammate must fold it into the marker.
    """

    def _run(self, *, in_place: bool, child_pid: int) -> str | None:
        """Drive main() with run_with_tee stubbed to invoke on_spawn (as the
        real one does right after Popen). Returns the marker content observed
        DURING the run, or None if no marker existed."""
        import tempfile
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        name = "worktree-story-001"
        seen: dict[str, str | None] = {}

        def capture_tee(cmd, *, on_spawn=None, **kw):
            if on_spawn is not None:
                on_spawn(child_pid)
            path = worktree.in_place_marker_path(self.smm_dir, name)
            seen["during"] = path.read_text() if path.is_file() else None
            return False

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        argv = [
            "--name",
            name,
            "--smm-dir",
            str(self.smm_dir),
            "--prompt-file",
            prompt_path,
        ]
        if in_place:
            argv.append("--in-place")
        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(argv)
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return seen.get("during")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_marker_records_both_supervisor_and_child_pids(self):
        """During the run the marker lists BOTH pids, so the episode reads live
        while EITHER is alive."""
        content = self._assert_not_none(self._run(in_place=True, child_pid=424242))
        self.assertEqual(
            content.split(),
            [str(os.getpid()), "424242"],
            "marker must list the supervisor's pid AND the child's",
        )

    def test_live_child_keeps_the_marker_alive_after_the_supervisor_dies(self):
        """End-to-end of the fix: take the marker spawn_teammate actually wrote,
        then simulate the supervisor being SIGKILLed by swapping its (live) pid
        for a dead one. The child is still running, so the episode must still
        read LIVE and the marker must survive.

        Positive control below: same marker, same code path, child dead too."""
        import worktree

        with live_pid() as child:
            self._assert_not_none(self._run(in_place=True, child_pid=child))
            marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
            marker.write_text(f"{dead_pid()} {child}")

            self.assertTrue(worktree.has_live_in_place_teammate(self.smm_dir))
            self.assertTrue(marker.exists(), "live child must keep its marker")

    def test_control_dead_child_lets_the_marker_go(self):
        """Positive control for the test above. Identical in every way — same
        spawn, same marker file, same probe — except the child is dead rather
        than alive. Proves the "stays live" assertion above tracks the child's
        liveness, and is not just a probe that can never go false.
        """
        import worktree

        self._assert_not_none(self._run(in_place=True, child_pid=dead_pid()))
        marker = worktree.in_place_marker_path(self.smm_dir, "worktree-story-001")
        marker.write_text(f"{dead_pid()} {dead_pid()}")

        self.assertFalse(worktree.has_live_in_place_teammate(self.smm_dir))
        self.assertFalse(marker.exists(), "fully-dead episode must be reaped")

    def test_worktree_spawn_passes_no_on_spawn_callback(self):
        """A worktree spawn writes no in-place marker, so it must not register
        the callback either — nothing to record into."""
        self.assertIsNone(self._run(in_place=False, child_pid=424242))


class TestSupervisorOnlyRemovesItsOwnMarker(unittest.TestCase):
    """The SECOND door onto the same disaster.

    The reap (in_place_marker) is one unguarded unlink on the marker path; the
    supervisor's `finally` is the other, with the identical blast radius. If a
    same-name teammate is respawned while the old supervisor is still running,
    the old supervisor's `finally` deletes the LIVE teammate's marker — and the
    three existence-only consumers then read "not a teammate", demoting it to the
    lead and misattributing its commits.

    This door is narrower than the reap's, but it is not closed: Python installs
    no SIGTERM handler, so a SIGKILLed or SIGTERMed spawn skips `finally`
    entirely (which is exactly why leaked markers are routine) — but the
    clean-exit and SIGINT paths DO run it.

    The predicate: delete the marker only if it is OURS and unchanged. Ownership
    is proven by CONTENT, not by a remembered stat — the marker's first pid is
    the supervisor that wrote it, i.e. us, and a pid cannot be recycled while its
    process is alive, so no respawn can forge it. The unchanged half is the same
    inode identity the reap uses.

    Control for both tests below: `test_in_place_marker_present_during_run_
    absent_after` — an unraced clean exit still removes its own marker.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"

    def _run_with_respawn(self, respawn) -> Path:
        """Drive an in-place main() to a clean exit, invoking `respawn` at the
        exact point the supervisor has recorded its own marker (on_spawn, which
        the real run_with_tee calls right after Popen). `respawn` simulates a
        same-name teammate being re-spawned mid-flight. Returns the marker path.
        """
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        def capture_tee(cmd, *, on_spawn=None, **kw):
            if on_spawn is not None:
                on_spawn(424242)
            respawn()
            return False

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=capture_tee),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        self.name,
                        "--smm-dir",
                        str(self.smm_dir),
                        "--prompt-file",
                        prompt_path,
                        "--in-place",
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)
        return worktree.in_place_marker_path(self.smm_dir, self.name)

    def test_respawned_marker_survives_the_old_supervisors_finally(self):
        """The headline race, shaped exactly as production produces it.

        A real respawn is a DIFFERENT supervisor process publishing a fresh
        marker, so its marker differs from ours in both ways that matter: a
        foreign supervisor pid (content) and a fresh inode. write_text_atomic
        stands in for that publisher — reached directly here only because
        claim_in_place_marker necessarily stamps the CALLER's pid, and this test
        process is the old supervisor.

        That distinction is the whole point rather than a testing detail: a
        respawn cannot share our pid, because a pid cannot be recycled while its
        process is alive. That is what makes the marker's first pid an
        unforgeable proof of ownership.
        """
        import worktree
        from _append_impl import write_text_atomic

        marker = worktree.in_place_marker_path(self.smm_dir, self.name)
        respawn_supervisor = dead_pid()

        with live_pid() as respawn_child:
            self._run_with_respawn(
                lambda: write_text_atomic(
                    marker, f"{respawn_supervisor} {respawn_child}"
                )
            )

            self.assertTrue(
                marker.exists(),
                "the old supervisor's finally deleted a live respawn's marker",
            )
            self.assertTrue(
                worktree.in_place_teammate_from_env(self.smm_dir, self.name),
                "...demoting the respawned teammate to the lead",
            )
            self.assertTrue(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "the respawn's marker must still read LIVE afterwards",
            )

    def test_a_failed_write_removes_nothing_even_when_the_pid_matches(self):
        """The ownership proof's unstated premise: WE wrote the marker at the path.

        Content is unforgeable only because a live pid cannot be recycled — but
        that argument covers a marker whose supervisor is ALIVE. A marker leaked
        by a SIGKILLed supervisor (routine: no SIGTERM handler, so its finally is
        skipped) names a DEAD pid, and a dead pid can be recycled — to us. Its
        child can still be running, so the marker is live.

        If our own marker write raises (ENOSPC/EACCES; write_text_atomic renames
        last, so nothing lands), the finally would otherwise read that stranger's
        marker, find our pid at the front, and delete a LIVE teammate's marker —
        the exact disaster this story exists to prevent, reached through the one
        path where "the first pid is ours" does NOT mean "we wrote it".

        So the removal is gated on our write having landed, not merely on
        --in-place.
        """
        from unittest.mock import patch

        import spawn_teammate
        import worktree

        marker = worktree.in_place_marker_path(self.smm_dir, self.name)

        def boom(*a, **kw):
            raise OSError("no space left on device")

        with live_pid() as orphaned_child:
            # A previous episode's leaked marker: its supervisor is dead and its
            # pid has been recycled to us, but its child is still running.
            marker.write_text(f"{os.getpid()} {orphaned_child}")

            def never_spawn(*_a, **_kw):
                # run_with_tee is patched UNCONDITIONALLY, even though `boom`
                # above is expected to stop main() long before it. The safety of
                # a test must never rest on the correctness of the thing it is
                # testing: if the claim stops raising, main() falls through to
                # here — and unstubbed, that launches a REAL `claude -p`, which
                # comes up with the plugin loaded, runs the suite, and re-enters
                # this test. Fail loudly instead.
                raise AssertionError(
                    "run_with_tee was reached: main() would have launched a REAL "
                    "`claude -p`"
                )

            with (
                patch.object(spawn_teammate, "create_worktree", return_value="/tmp/wt"),
                patch.object(spawn_teammate, "run_with_tee", side_effect=never_spawn),
                patch.object(
                    spawn_teammate.in_place_marker, "claim_in_place_marker", boom
                ),
                self.assertRaises(OSError),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        self.name,
                        "--smm-dir",
                        str(self.smm_dir),
                        "--prompt-file",
                        "/nonexistent-prompt.txt",
                        "--in-place",
                    ]
                )

            self.assertTrue(
                marker.exists(),
                "a marker we never wrote must not be removed by our finally",
            )
            self.assertTrue(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "...its orphaned child is still live",
            )

    def test_a_marker_naming_another_supervisor_is_never_deleted(self):
        """Isolates the ownership leg from the inode leg.

        Here the respawn rewrites the marker IN PLACE (write_text truncates), so
        the file keeps its inode. Ownership is then the only thing that can save
        it — and it does, because the first pid is not ours. Content is what
        proves the marker is someone else's; the inode only proves it has not
        changed since we read it.
        """
        import worktree

        marker = worktree.in_place_marker_path(self.smm_dir, self.name)
        other_supervisor = dead_pid()

        with live_pid() as child:
            self._run_with_respawn(
                lambda: marker.write_text(f"{other_supervisor} {child}")
            )
            self.assertTrue(
                marker.exists(),
                "a marker naming a DIFFERENT supervisor must never be deleted",
            )


if __name__ == "__main__":
    unittest.main()
