#!/usr/bin/env python3
"""End-to-end tests for the marker WRITE door, driven through spawn_teammate.main.

The primitives (claim, guarded rewrite) are unit-tested in
test_in_place_marker_claim.py. This file drives them through the real supervisor
lifecycle, which is where the reported failure actually lived:

    A claims [A] -> B publishes [B, B_child] -> A's on_spawn CLOBBERS to [A, A_child]
    -> A's finally reads tokens[0] == A -> ownership PASSES -> UNLINK

A deletes live teammate B's marker, demoting B to the lead and misattributing its
commits. A writer can forge the content proof against itself, which is why
ownership must be established by TAKING the name, not by writing it.

Split from test_in_place_marker_claim.py at the 500-line ceiling.

SAFETY: every test here patches run_with_tee UNCONDITIONALLY, including the ones
that expect main() to refuse before it spawns. A test's safety must never depend
on the correctness of the thing it is testing — in the TDD red phase the refusal
did not exist, main() fell through, and it launched real recursive `claude -p`
agents. conftest's subprocess.Popen backstop is the second line of defence.
"""

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
from conftest import dead_pid, live_pid


def _never_spawn(*_args, **_kwargs):
    """run_with_tee stub for tests that expect main() to REFUSE before spawning.

    Every test that calls spawn_teammate.main() must patch run_with_tee
    unconditionally, INCLUDING the ones that expect a refusal — never let the
    safety of a test depend on the correctness of the thing it is testing.

    These two tests assert that the claim refuses a held name. Before the claim
    existed (the TDD red phase) it did not refuse, so main() fell straight through
    to run_with_tee and launched a REAL `claude -p` — which came up in the repo
    with the plugin loaded, ran the suite, re-entered this test, and spawned
    another. spawn_teammate is a plain Popen with no start_new_session, so those
    children reparented to init and outlived the run. ~20 real billable agents.

    This stub makes that structurally impossible: if main() ever gets past the
    claim, the test fails LOUDLY here instead of launching an agent. A red test
    must be INCAPABLE of spawning, not merely expected not to.
    """
    raise AssertionError(
        "run_with_tee was reached: main() got past the claim and would have "
        "launched a REAL `claude -p`. The claim must refuse a held name."
    )


class TestWriteDoorEndToEnd(unittest.TestCase):
    """The reported sequence, driven through spawn_teammate.main.

    The old supervisor A is this test process. B is a respawn that takes the
    marker path while A is mid-flight — reachable in production once the marker
    has been cleared out-of-band. B's marker is published through an atomic
    rename (a NEW inode), which is what any real publisher does; an in-place
    truncate would preserve st_ino and st_size and leave the guard resting on a
    ~70us st_mtime_ns delta that Linux's coarse 1-4ms mtime clock cannot resolve
    (decision 07f346cdf7f7).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.smm_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.name = "worktree-story-001"
        self.marker = worktree.in_place_marker_path(self.smm_dir, self.name)

    def _run_with_respawn_before_on_spawn(self, respawn) -> None:
        """Drive an in-place main() to a clean exit, firing `respawn` BEFORE
        on_spawn records the child's pid — i.e. inside the window where the old
        supervisor still has an unconditional write ahead of it.

        The existing door-2 test fires its respawn AFTER on_spawn, which is why
        it passes without this fix: A's clobbering write has already happened.
        """
        import spawn_teammate

        def capture_tee(cmd, *, on_spawn=None, **kw):
            respawn()
            if on_spawn is not None:
                on_spawn(424242)
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

    def test_a_live_respawns_marker_survives_the_old_supervisors_child_write(self):
        """The headline: A must neither overwrite B's marker nor delete it."""
        from _append_impl import write_text_atomic

        with live_pid() as b_child:
            b_content = f"{dead_pid()} {b_child}"
            self._run_with_respawn_before_on_spawn(
                lambda: write_text_atomic(self.marker, b_content)
            )

            self.assertTrue(
                self.marker.exists(),
                "A overwrote B's marker with its own pids, then its finally saw "
                "its own pid at the front and deleted a LIVE teammate's marker",
            )
            self.assertEqual(
                self.marker.read_text(),
                b_content,
                "A must not re-forge ownership by overwriting B's marker",
            )

    def test_the_respawned_teammate_is_not_demoted_to_lead(self):
        """...and the consequence that actually bites."""
        from _append_impl import write_text_atomic

        with live_pid() as b_child:
            self._run_with_respawn_before_on_spawn(
                lambda: write_text_atomic(self.marker, f"{dead_pid()} {b_child}")
            )

            self.assertTrue(
                worktree.in_place_teammate_from_env(self.smm_dir, self.name),
                "B was demoted to the lead: its skill gating drops and its "
                "commits are misattributed",
            )
            self.assertTrue(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "B's child is still running — the episode must read LIVE",
            )

    def test_spawning_over_a_live_teammate_refuses_and_spares_its_marker(self):
        """The first write door, end to end: main() must fail loud rather than
        clobber, and its finally must not delete the marker it never wrote."""
        import spawn_teammate

        with live_pid() as b_child:
            b_content = f"{dead_pid()} {b_child}"
            self.marker.write_text(b_content)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write("test prompt")
                prompt_path = f.name

            try:
                with (
                    patch.object(
                        spawn_teammate, "create_worktree", return_value="/tmp/wt"
                    ),
                    patch.object(
                        spawn_teammate, "run_with_tee", side_effect=_never_spawn
                    ),
                    self.assertRaises(in_place_marker.InPlaceNameHeld),
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

            self.assertEqual(
                self.marker.read_text(),
                b_content,
                "the refused spawn must leave the live holder's marker untouched",
            )

    def test_a_refused_spawn_spares_the_live_holders_story_assignment(self):
        """Sparing the marker is not enough — the refusal must have NO effect on
        the live holder at all.

        The name-keyed .story-assignment is the Tier-1 attribution signal that the
        marker GATES: commit_event._resolve_story_id trusts it precisely because a
        live marker vouches for the name. So clobbering it while sparing the marker
        is the worst of both worlds — B stays a teammate and its commits are
        attributed to A's story, which is the very harm the claim exists to
        prevent, reached through a different door.

        Every side effect that keys off the NAME must therefore land AFTER the
        claim has taken it, never before.
        """
        import spawn_teammate

        assignment = worktree.story_assignment_path(self.smm_dir, self.name)

        with live_pid() as b_child:
            self.marker.write_text(f"{dead_pid()} {b_child}")
            assignment.write_text("story-B")

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                # Must NAME story-A: the prompt guard (story-014) refuses a prompt
                # that does not name the story being spawned, and it runs BEFORE
                # the claim — a prompt that fails it never reaches the claim door
                # this test exists to exercise. (Both guards defend the same
                # invariant from different sides: no name-keyed side effect for a
                # spawn that will be refused.)
                f.write("test prompt for story-A")
                prompt_path = f.name

            try:
                with (
                    patch.object(
                        spawn_teammate, "create_worktree", return_value="/tmp/wt"
                    ),
                    patch.object(
                        spawn_teammate, "run_with_tee", side_effect=_never_spawn
                    ),
                    self.assertRaises(in_place_marker.InPlaceNameHeld),
                ):
                    spawn_teammate.main(
                        [
                            "--name",
                            self.name,
                            "--smm-dir",
                            str(self.smm_dir),
                            "--prompt-file",
                            prompt_path,
                            "--story-id",
                            "story-A",
                            "--in-place",
                        ]
                    )
            finally:
                Path(prompt_path).unlink(missing_ok=True)

            self.assertEqual(
                assignment.read_text(),
                "story-B",
                "the refused spawn overwrote the LIVE holder's story assignment — "
                "its commits now attribute to the story that failed to spawn",
            )


if __name__ == "__main__":
    unittest.main()
