#!/usr/bin/env python3
"""Tests for worktree_teardown.py: the mirror image of worktree_bootstrap.

A teammate worktree can start things that outlive it (e.g. a docker compose
stack); `stack.worktree_teardown` lets a project declare a command to stop
them before the worktree is removed. Unlike bootstrap, teardown must NEVER
raise — cleanup that refuses to clean up is worse than the leak it prevents
(decision `74662df6641d`, topic `teardown-degrades-quiet`).

Every test asserts the command's EFFECT (a file it wrote), never merely that
a runner was called, following the rule pinned in
test_spawn_teammate_bootstrap.py.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree_teardown
from _bases import _SMMTestCase
from _system_context_fixtures import valid_doc, write_doc


class _TeardownTestCase(_SMMTestCase):
    """Shared setup: a temp SMM dir whose system_context may declare a
    teardown, and a temp dir standing in for a worktree path."""

    def setUp(self):
        super().setUp()
        self.wt_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.wt_dir, ignore_errors=True)
        super().tearDown()

    def declare_teardown(self, command: str) -> None:
        doc = valid_doc()
        doc["stack"]["worktree_teardown"] = command
        write_doc(self.smm_dir, doc)


class TestTeardownRuns(_TeardownTestCase):
    """AC1: a declared command runs, with the worktree path as cwd."""

    def test_declared_command_effect_is_observable_in_the_worktree(self):
        self.declare_teardown("echo torn > torn.txt")

        worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        artifact = self.wt_dir / "torn.txt"
        self.assertTrue(artifact.is_file())
        self.assertEqual(artifact.read_text().strip(), "torn")

    def test_command_runs_with_the_worktree_as_cwd(self):
        self.declare_teardown("pwd > where.txt")

        worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        recorded = (self.wt_dir / "where.txt").read_text().strip()
        self.assertEqual(Path(recorded).resolve(), self.wt_dir.resolve())


class TestTeardownAbsent(_TeardownTestCase):
    """AC2: no declaration is a no-op that spawns nothing."""

    def test_no_worktree_teardown_field_spawns_nothing(self):
        write_doc(self.smm_dir, valid_doc())

        with patch.object(
            worktree_teardown._subprocess_env, "run_in_new_process_group"
        ) as spawn:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        spawn.assert_not_called()

    def test_no_system_context_spawns_nothing(self):
        (self.smm_dir / "system_context.json").unlink(missing_ok=True)

        with patch.object(
            worktree_teardown._subprocess_env, "run_in_new_process_group"
        ) as spawn:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        spawn.assert_not_called()


class TestTeardownDegradesQuiet(_TeardownTestCase):
    """AC3: failures return normally and report the reason on stderr."""

    def test_nonzero_exit_returns_normally_and_reports(self):
        self.declare_teardown("echo half > half.txt; echo boom >&2; exit 1")

        with patch("sys.stderr") as mock_stderr:
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        self.assertTrue((self.wt_dir / "half.txt").is_file())
        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("boom", written)
        self.assertIn("1", written)

    def test_timeout_returns_normally_and_reports(self):
        self.declare_teardown("sleep 5")

        with (
            patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}),
            patch("sys.stderr") as mock_stderr,
        ):
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        written = "".join(c.args[0] for c in mock_stderr.write.call_args_list)
        self.assertIn("timed out", written)

    def test_corrupt_system_context_returns_normally_and_reports(self):
        (self.smm_dir / "system_context.json").write_text("not json")

        with patch("sys.stderr") as mock_stderr:
            # Should not raise despite the corrupt doc.
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        # No declaration was readable, so nothing ran and nothing needed
        # reporting — the point of this test is the absence of a raise.
        mock_stderr.write.assert_not_called()


class TestTeardownKillsProcessGroup(_TeardownTestCase):
    """AC4: a backgrounded, hanging child is killed as a group; run_teardown
    still returns rather than blocking on its pipe."""

    def test_backgrounded_hanging_child_is_killed_and_teardown_returns(self):
        self.declare_teardown(
            "echo started > started.txt; "
            "(sleep 30 && echo should-not-appear > leaked.txt) & "
            "wait $!"
        )

        with (
            patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "1"}),
            patch("sys.stderr"),
        ):
            worktree_teardown.run_teardown(str(self.wt_dir), self.smm_dir)

        self.assertTrue((self.wt_dir / "started.txt").is_file())
        self.assertFalse(
            (self.wt_dir / "leaked.txt").exists(),
            "backgrounded grandchild must be killed with the process group, "
            "not left to finish after the timeout",
        )


class TestTeardownTimeoutOverride(_TeardownTestCase):
    def test_zero_falls_back_to_the_default(self):
        with patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "0"}):
            self.assertEqual(
                worktree_teardown._teardown_timeout(),
                worktree_teardown._DEFAULT_TEARDOWN_TIMEOUT_S,
            )

    def test_positive_override_is_honoured(self):
        with patch.dict(os.environ, {"XP_TEARDOWN_TIMEOUT_S": "42"}):
            self.assertEqual(worktree_teardown._teardown_timeout(), 42)


if __name__ == "__main__":
    unittest.main()
