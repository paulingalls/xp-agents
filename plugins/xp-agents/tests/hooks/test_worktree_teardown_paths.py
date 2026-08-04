#!/usr/bin/env python3
"""Tests for the removal choke point in worktree.remove_worktree_dir:
teardown runs before removal, and the coordination entry clears after a
removal that actually succeeded.

story-001 shipped `worktree_teardown.run_teardown` wired to nothing, and
`coordination.clear_coordination_agent` has never been called from a
worktree-removal path. story-002 wires both into `remove_worktree_dir` — the
single choke point every removal path funnels through.

Two increments, mirroring the story's TDD split:
  - TestTeardown*        : AC1, AC2, AC4 (teardown wiring)
  - TestCoordination*    : AC3, AC4, AC5, AC6 (coordination clear)
"""

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import post_tool_use
import worktree
from _repo_bases import _create_teammate_worktree
from _system_context_fixtures import valid_doc, write_doc
from conftest import _IntegrationTestCase


class _TeardownWiringTestCase(_IntegrationTestCase):
    """Shared helper: declare a project teardown command via system_context."""

    def declare_teardown(self, command: str) -> None:
        doc = valid_doc()
        doc["stack"]["worktree_teardown"] = command
        write_doc(self.smm_dir, doc)


class TestTeardownRunsBeforeRemoval(_TeardownWiringTestCase):
    """AC1: a declared teardown command runs at the worktree path, before
    the directory is removed — only when force=True and smm_dir is given."""

    def test_declared_command_effect_is_observable_and_worktree_is_removed(self):
        name = "worktree-story-201"
        # Written OUTSIDE the worktree (to $SMM_DIR) — an artifact written
        # INSIDE would be destroyed by the removal this same call performs,
        # making it impossible to distinguish "ran" from "never ran".
        self.declare_teardown('echo torn > "$SMM_DIR/torn.txt"')
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))

        worktree.remove_worktree_dir(
            name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
        )

        artifact = self.smm_dir / "torn.txt"
        self.assertTrue(artifact.is_file(), "declared teardown command never ran")
        self.assertEqual(artifact.read_text().strip(), "torn")
        self.assertFalse(wt_path.is_dir(), "worktree directory should be removed")

    def test_teardown_is_called_while_the_worktree_still_exists(self):
        """Explicit ordering proof: run_teardown fires while the directory
        it's handed still exists on disk — i.e. strictly before removal."""
        name = "worktree-story-205"
        self.declare_teardown('echo torn > "$SMM_DIR/torn.txt"')
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))
        observed_still_present = {}

        real_run_teardown = worktree.worktree_teardown.run_teardown

        def spy(wt_arg, smm_dir_arg):
            observed_still_present["value"] = Path(wt_arg).is_dir()
            observed_still_present["path"] = wt_arg
            observed_still_present["smm_dir"] = smm_dir_arg
            return real_run_teardown(wt_arg, smm_dir_arg)

        with patch(
            "worktree.worktree_teardown.run_teardown", side_effect=spy
        ) as mock_teardown:
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
            )

        mock_teardown.assert_called_once()
        self.assertTrue(
            observed_still_present.get("value"),
            "run_teardown must be called while the worktree directory still exists",
        )
        self.assertEqual(observed_still_present["path"], str(wt_path))
        self.assertEqual(observed_still_present["smm_dir"], self.smm_dir)
        self.assertFalse(wt_path.is_dir(), "worktree directory should end up removed")


class TestNoTeardownWithoutForceOrSmmDir(_TeardownWiringTestCase):
    """AC2: force=False must never run teardown — the tree may belong to a
    live peer whose stack we must not touch. Also: no smm_dir, no teardown
    (nothing to read a declaration from)."""

    def test_force_false_skips_teardown(self):
        name = "worktree-story-202"
        self.declare_teardown('echo should-not-run > "$SMM_DIR/leak.txt"')
        _create_teammate_worktree(self.tmpdir, name)

        with patch("worktree.worktree_teardown.run_teardown") as mock_teardown:
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=False, smm_dir=self.smm_dir
            )

        mock_teardown.assert_not_called()
        self.assertFalse((self.smm_dir / "leak.txt").exists())

    def test_no_smm_dir_skips_teardown(self):
        name = "worktree-story-206"
        self.declare_teardown('echo should-not-run > "$SMM_DIR/leak2.txt"')
        _create_teammate_worktree(self.tmpdir, name)

        with patch("worktree.worktree_teardown.run_teardown") as mock_teardown:
            worktree.remove_worktree_dir(name, str(self.tmpdir), force=True)

        mock_teardown.assert_not_called()


class TestTeardownTargetMustBeALinkedWorktree(_TeardownWiringTestCase):
    """`run_teardown` validates nothing about `wt_path` by design — it
    documents that the CALLER owns confirming the path is a real worktree.
    This choke point is that caller, and `is_dir()` alone does not discharge
    the obligation: a stranded directory and the lead's own main checkout are
    both directories. Running a project's declared stop command in either is
    the scoping failure the milestone forbids."""

    def test_no_teardown_in_a_directory_that_is_not_a_worktree(self):
        """A run killed between mkdir and `git worktree add` strands a plain
        directory at the worktree path. Nothing was ever started in it, so
        nothing may be stopped there."""
        name = "worktree-story-207"
        self.declare_teardown('echo torn > "$SMM_DIR/stray.txt"')
        wt = worktree.worktree_path(name, str(self.tmpdir))
        wt.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, wt, True)

        worktree.remove_worktree_dir(
            name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
        )

        self.assertFalse(
            (self.smm_dir / "stray.txt").exists(),
            "teardown must not run in a directory that is not a linked worktree",
        )

    def test_no_teardown_in_the_main_checkout(self):
        """The named risk, directly: whatever a caller's `name` resolves to,
        the lead's own checkout must never have the project's stop command
        run against it."""
        self.declare_teardown('echo torn > "$SMM_DIR/main-checkout.txt"')

        with patch("worktree.worktree_path", return_value=self.tmpdir):
            worktree.remove_worktree_dir(
                "worktree-story-208",
                str(self.tmpdir),
                force=True,
                smm_dir=self.smm_dir,
            )

        self.assertFalse(
            (self.smm_dir / "main-checkout.txt").exists(),
            "teardown must never run against the main checkout",
        )
        self.assertTrue(
            (self.tmpdir / "README").is_file(), "the main checkout must survive"
        )


class TestRemovalSurvivesTeardownFailure(_TeardownWiringTestCase):
    """AC4 (removal half): a failing/timing-out teardown command must not
    block the worktree from being removed."""

    def test_worktree_still_removed_when_teardown_command_fails(self):
        name = "worktree-story-203"
        self.declare_teardown("exit 1")
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))

        worktree.remove_worktree_dir(
            name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
        )

        self.assertFalse(
            wt_path.is_dir(), "removal must proceed despite a failing teardown"
        )

    def test_worktree_still_removed_when_teardown_times_out(self):
        name = "worktree-story-204"
        self.declare_teardown("sleep 5")
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))

        with patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}):
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
            )

        self.assertFalse(
            wt_path.is_dir(), "removal must proceed despite a timed-out teardown"
        )


class TestCoordinationClearsOnSuccessfulRemoval(_IntegrationTestCase):
    """AC3: the coordination entry a real hook registered is cleared by name
    after the worktree it belongs to is removed — and a sibling's entry is
    left untouched.

    The registered key is never hand-typed: it comes out of a real
    post_tool_use.run() call over realistic hook input, so this proves the
    production register-then-clear round trip, not a coincidence of two
    identical literals.
    """

    def test_clears_the_key_post_tool_use_actually_registered(self):
        name = "worktree-story-301"
        other = "worktree-story-302"
        wt_path = _create_teammate_worktree(self.tmpdir, name)
        other_wt_path = _create_teammate_worktree(self.tmpdir, other)

        post_tool_use.run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "notes.txt"},
                "cwd": wt_path,
            },
            smm_dir=self.smm_dir,
        )
        post_tool_use.run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "notes.txt"},
                "cwd": other_wt_path,
            },
            smm_dir=self.smm_dir,
        )

        before = coordination.read_coordination(self.smm_dir)
        self.assertIn(
            name,
            before,
            "post_tool_use should have registered this teammate under its own key",
        )
        self.assertIn(other, before)

        worktree.remove_worktree_dir(
            name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
        )

        after = coordination.read_coordination(self.smm_dir)
        self.assertNotIn(
            name,
            after,
            "the key post_tool_use registered for the removed teammate must be cleared",
        )
        self.assertIn(other, after, "a sibling teammate's entry must be untouched")

    def test_clears_despite_a_failing_teardown_command(self):
        """AC4 (coordination half): a failing teardown must not prevent the
        coordination entry from clearing once removal succeeds."""
        name = "worktree-story-303"
        wt_path = _create_teammate_worktree(self.tmpdir, name)
        doc = valid_doc()
        doc["stack"]["worktree_teardown"] = "exit 1"
        write_doc(self.smm_dir, doc)

        post_tool_use.run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "notes.txt"},
                "cwd": wt_path,
            },
            smm_dir=self.smm_dir,
        )
        self.assertIn(name, coordination.read_coordination(self.smm_dir))

        worktree.remove_worktree_dir(
            name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
        )

        self.assertNotIn(name, coordination.read_coordination(self.smm_dir))


class TestCoordinationNotClearedOnRefusal(_IntegrationTestCase):
    """AC5: force=False refusing on a dirty worktree raises WorktreeNotEmpty
    and must NOT clear the coordination entry — the tree is still there, so
    the entry is not phantom."""

    def test_raise_leaves_the_coordination_entry_in_place(self):
        name = "worktree-story-304"
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))
        (wt_path / "untracked.txt").write_text("uncommitted work")
        coordination.update_coordination(self.smm_dir, name, ["untracked.txt"])

        with self.assertRaises(worktree.WorktreeNotEmpty):
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=False, smm_dir=self.smm_dir
            )

        self.assertIn(
            name,
            coordination.read_coordination(self.smm_dir),
            "a refused removal must not clear the entry for a tree that's still there",
        )
        self.assertTrue(wt_path.is_dir())


class TestCoordinationNotClearedOnRemovalFailure(_IntegrationTestCase):
    """AC6: `git worktree remove --force` reporting failure must not clear
    the coordination entry — the tree still exists, so the entry is not
    phantom."""

    def test_failed_force_removal_leaves_the_coordination_entry_in_place(self):
        import subprocess

        name = "worktree-story-305"
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))
        coordination.update_coordination(self.smm_dir, name, ["x"])

        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd[:3] == ["git", "worktree", "remove"]:
                return subprocess.CompletedProcess(
                    cmd, returncode=1, stdout="", stderr="simulated failure"
                )
            return real_run(cmd, *args, **kwargs)

        with patch("worktree.subprocess.run", side_effect=fake_run):
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
            )

        self.assertTrue(wt_path.is_dir(), "tree should still exist")
        self.assertIn(
            name,
            coordination.read_coordination(self.smm_dir),
            "a failed force-removal must not clear the entry for a tree still there",
        )


class TestFailedForceRemovalIsReported(_IntegrationTestCase):
    """A forced removal that FAILS is the one outcome nobody hears about.

    `force=False` raises `WorktreeNotEmpty`; `force=True` has no such exit —
    the return value carries only the branch, and every caller reads it as
    "the tree is gone". Withholding the coordination clear (the class above)
    is a withheld side effect, not a report: without this the stale worktree
    sits there unmentioned until someone trips over it.
    """

    def test_a_failed_force_removal_names_the_path_and_gits_reason(self):
        import io
        import subprocess
        from contextlib import redirect_stderr

        name = "worktree-story-306"
        wt_path = Path(_create_teammate_worktree(self.tmpdir, name))
        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd[:3] == ["git", "worktree", "remove"]:
                return subprocess.CompletedProcess(
                    cmd, returncode=1, stdout="", stderr="simulated git refusal"
                )
            return real_run(cmd, *args, **kwargs)

        err = io.StringIO()
        with (
            patch("worktree.subprocess.run", side_effect=fake_run),
            redirect_stderr(err),
        ):
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
            )

        message = err.getvalue()
        self.assertIn(str(wt_path), message, "the operator needs the PATH")
        self.assertIn("simulated git refusal", message, "git's own reason must survive")

    def test_a_successful_force_removal_says_nothing(self):
        """The refutation: a report that fires on the happy path is noise, and
        noise is how a real one gets ignored."""
        import io
        from contextlib import redirect_stderr

        name = "worktree-story-307"
        _create_teammate_worktree(self.tmpdir, name)

        err = io.StringIO()
        with redirect_stderr(err):
            worktree.remove_worktree_dir(
                name, str(self.tmpdir), force=True, smm_dir=self.smm_dir
            )

        self.assertNotIn("removal FAILED", err.getvalue())


class TestRespawnRunsTheDeclaredTeardown(_TeardownWiringTestCase):
    """The CALL SITE half of the wiring, which no `remove_worktree_dir` test
    can reach.

    Teardown is opt-in per call site (`smm_dir=None` by default, deliberately —
    ~15 tests create throwaway worktrees through `create_worktree` and must not
    fire the developer's own declared command). Opt-in means a call site that
    forgets makes the feature inert THERE while the whole choke-point suite
    stays green — which is exactly what happened to `cleanup_existing`'s forced
    arm: a re-spawn clearing a stale tree with a live stack tore down nothing.
    """

    def test_respawn_clearing_a_stale_worktree_runs_the_teardown(self):
        """Mutation: drop `smm_dir=smm_dir` from either `cleanup_existing`'s
        `remove_worktree` call or `create_worktree`'s `cleanup_existing` call
        -> red. The artifact is written to $SMM_DIR, OUTSIDE the worktree, so
        the removal that follows cannot destroy the evidence."""
        import spawn_teammate

        name = "worktree-story-308"
        self.declare_teardown('echo torn > "$SMM_DIR/respawn-torn.txt"')
        _create_teammate_worktree(self.tmpdir, name)

        spawn_teammate.create_worktree(name, str(self.tmpdir), smm_dir=self.smm_dir)

        self.assertTrue(
            (self.smm_dir / "respawn-torn.txt").is_file(),
            "the re-spawn's forced removal must run the declared teardown; "
            "without it a stale tree's services outlive the worktree",
        )

    def test_a_respawn_without_an_smm_dir_still_never_tears_down(self):
        """The other half of opt-in: no ambient resolution, ever."""
        import spawn_teammate

        name = "worktree-story-309"
        self.declare_teardown('echo leaked > "$SMM_DIR/respawn-leak.txt"')
        _create_teammate_worktree(self.tmpdir, name)

        spawn_teammate.create_worktree(name, str(self.tmpdir))

        self.assertFalse((self.smm_dir / "respawn-leak.txt").exists())


if __name__ == "__main__":
    unittest.main()
