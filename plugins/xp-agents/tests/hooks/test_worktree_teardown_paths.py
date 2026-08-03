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
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

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


if __name__ == "__main__":
    unittest.main()
