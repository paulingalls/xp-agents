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
    """The reported sequence, driven through spawn_teammate.main — and how the
    lock DISSOLVES it rather than guarding it.

    The old sequence needed a rival supervisor B to publish a marker under a name
    A was already running. Ownership was proven by CONTENT, so A's next write
    re-forged that proof against itself and A's finally then deleted B's LIVE
    marker.

    Under the holder lock, B cannot exist. A holds the name for its whole episode,
    and a lock cannot be forged — so B's claim is REFUSED before it publishes
    anything, and there is no foreign marker for A to clobber or delete. The tests
    below therefore pin the DISSOLUTION: the rival is turned away at the door
    (test 1), and merely writing bytes into the marker file — which is all the old
    fixtures ever did — does not make anyone an owner (test 2).
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
        supervisor still has a write ahead of it, which is where the clobber used
        to land."""
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

    def test_a_respawn_cannot_take_the_name_while_the_supervisor_is_mid_flight(self):
        """The whole bug class, closed at the door.

        A rival claim fired at the exact moment the old fixtures published B's
        marker — inside A's run, before A's child write — is REFUSED. B never
        publishes, so nothing A does afterwards can touch a live teammate's
        marker. Note the rival is refused even though it is THIS process: the
        holder lock conflicts across open file descriptions, not across pids, so
        "I already hold this name" is not something a claimant can talk its way
        out of.
        """
        refusals: list[Exception] = []

        def rival_claim() -> None:
            try:
                in_place_marker.claim_in_place_marker(self.smm_dir, self.name)
            except in_place_marker.InPlaceNameHeld as exc:
                refusals.append(exc)

        self._run_with_respawn_before_on_spawn(rival_claim)

        self.assertEqual(
            len(refusals),
            1,
            "a respawn took a name a LIVE supervisor was holding — two `claude` "
            "processes in one checkout, and whichever tears down first deletes "
            "the other's marker",
        )

    def test_writing_bytes_into_the_marker_does_not_make_you_its_owner(self):
        """Ownership is the LOCK, not the content — which is why the content can
        no longer be forged.

        Someone (an operator, a stale script) writes foreign pids into the marker
        file mid-episode. That is not a claim: the name is still A's, so A's child
        write and A's teardown are still operating on A's OWN marker, and the
        stray bytes are simply overwritten. Under the old content-proof this same
        fixture WAS a rival supervisor, and A's finally deleted its marker.
        """
        from _append_impl import write_text_atomic

        with live_pid() as stray_pid:
            self._run_with_respawn_before_on_spawn(
                lambda: write_text_atomic(self.marker, f"{dead_pid()} {stray_pid}")
            )

            self.assertFalse(
                self.marker.exists(),
                "the marker A published under a name A held is A's to remove",
            )
            self.assertFalse(
                worktree.has_live_in_place_teammate(self.smm_dir),
                "and once A is gone, nothing live remains under that name",
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
