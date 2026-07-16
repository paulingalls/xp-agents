#!/usr/bin/env python3
"""Tests for spawn_teammate's worktree bootstrap runner.

`git worktree add` materializes only tracked files, so every gitignored
artifact a project needs is absent from a fresh teammate worktree — and the
absence does not reliably fail loud. A project can declare
`stack.worktree_bootstrap`; spawn runs it in the new worktree before the agent
takes its first turn.

Every test here asserts the command's EFFECT (a file the command wrote,
inside the worktree), never merely that a runner was called: a call-count
assertion passes against an implementation that never runs anything.

The suite-wide spawn guard does NOT cover this file. It patches
subprocess.Popen to block argv[0] == "claude", but a shell=True bootstrap
runs /bin/sh, which the guard lets through. Every command declared below is
therefore deliberately harmless (writes a marker file, or exits non-zero).
"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import spawn_teammate
from _system_context_fixtures import valid_doc, write_doc
from conftest import _IntegrationTestCase, cleanup_test_worktrees


class _BootstrapTestCase(_IntegrationTestCase):
    """Shared setup: a temp git repo whose SMM may declare a bootstrap."""

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()

    def declare_bootstrap(self, command: str) -> None:
        """Declare `stack.worktree_bootstrap` in this repo's system_context."""
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = command
        write_doc(self.smm_dir, doc)

    def spawn(self, name: str = "worktree-story-bootstrap") -> str:
        """create_worktree with this test's SMM dir threaded in."""
        return spawn_teammate.create_worktree(
            name, str(self.tmpdir), smm_dir=self.smm_dir
        )


class TestBootstrapRuns(_BootstrapTestCase):
    """AC1: a declared command runs, in the worktree, before the agent."""

    def test_declared_command_effect_is_observable_in_the_worktree(self):
        self.declare_bootstrap("echo provisioned > generated.txt")

        wt_path = self.spawn()

        artifact = Path(wt_path) / "generated.txt"
        self.assertTrue(
            artifact.is_file(),
            "bootstrap must have run with the new worktree as cwd — its "
            f"artifact is missing from {wt_path}",
        )
        self.assertEqual(artifact.read_text().strip(), "provisioned")

    def test_command_runs_with_the_worktree_as_cwd_not_the_main_checkout(self):
        # The whole point of the feature: provisioning the NEW checkout. Both
        # runners this borrows from inherit the process cwd, which would
        # provision the main repo and leave the worktree as bare as before.
        self.declare_bootstrap("pwd > where.txt")

        wt_path = self.spawn()

        recorded = (Path(wt_path) / "where.txt").read_text().strip()
        self.assertEqual(
            Path(recorded).resolve(),
            Path(wt_path).resolve(),
            "bootstrap ran in the wrong directory",
        )
        self.assertFalse(
            (self.tmpdir / "where.txt").exists(),
            "bootstrap must not write into the main checkout",
        )

    def test_command_receives_resolved_smm_dir_in_its_env(self):
        # A relative SMM_DIR would resolve against the worktree, not the
        # parent — so the injected value must be absolute.
        self.declare_bootstrap('printf %s "$SMM_DIR" > smm-seen.txt')

        wt_path = self.spawn()

        seen = (Path(wt_path) / "smm-seen.txt").read_text().strip()
        self.assertEqual(Path(seen), self.smm_dir.resolve())
        self.assertTrue(Path(seen).is_absolute())


class TestBootstrapFailure(_BootstrapTestCase):
    """AC2: a failing bootstrap fails loud, and leaves the evidence."""

    def test_nonzero_exit_raises_with_command_and_output(self):
        self.declare_bootstrap("echo could-not-install >&2; exit 3")

        with self.assertRaises(SystemExit) as ctx:
            self.spawn()

        message = str(ctx.exception)
        self.assertIn("could-not-install", message, "captured output must surface")
        self.assertIn("3", message, "exit code must surface")
        self.assertIn("echo could-not-install", message, "the command must surface")

    def test_failed_bootstrap_leaves_the_worktree_for_forensics(self):
        # Auto-rollback would need force=True (bootstrap has already written
        # files), destroying the very evidence needed to debug the failure.
        self.declare_bootstrap("echo half-done > partial.txt; exit 1")
        name = "worktree-story-bootstrap"

        with self.assertRaises(SystemExit):
            self.spawn(name)

        import worktree

        wt = worktree.worktree_path(name, str(self.tmpdir))
        self.assertTrue(wt.is_dir(), "worktree must be left in place")
        self.assertTrue(
            (wt / "partial.txt").is_file(),
            "the partial bootstrap's output must survive for diagnosis",
        )


class TestBootstrapAbsent(_BootstrapTestCase):
    """AC3: undeclared → nothing runs, behavior unchanged."""

    def test_no_system_context_is_a_no_op(self):
        (self.smm_dir / "system_context.json").unlink(missing_ok=True)

        wt_path = self.spawn()

        self.assertTrue(Path(wt_path).is_dir())

    def test_no_worktree_bootstrap_field_is_a_no_op(self):
        write_doc(self.smm_dir, valid_doc())

        wt_path = self.spawn()

        self.assertTrue(Path(wt_path).is_dir())

    def test_no_smm_dir_argument_never_bootstraps(self):
        # ~15 existing callers create worktrees positionally, with no SMM dir.
        # An ambient env/init.sh read inside create_worktree would fire the
        # DEVELOPER's own declared bootstrap in every one of those worktrees.
        self.declare_bootstrap("echo leaked > leaked.txt")

        wt_path = spawn_teammate.create_worktree(
            "worktree-story-bootstrap", str(self.tmpdir)
        )

        self.assertFalse(
            (Path(wt_path) / "leaked.txt").exists(),
            "create_worktree without smm_dir must never resolve one ambiently",
        )


class TestInPlaceSkipsBootstrap(_BootstrapTestCase):
    """AC4: --in-place never reaches the bootstrap — structurally."""

    def test_in_place_run_cwd_never_flows_through_create_worktree(self):
        # main() reads `run_cwd = cwd if args.in_place else create_worktree(...)`,
        # so the bootstrap is unreachable in-place by construction rather than
        # by a guard someone could later drop. Asserted on the source because
        # the claim IS structural — there is no in-place code path that could
        # run a bootstrap for a behavioral test to observe NOT happening.
        # Whitespace-normalized: the line legally wraps as it grows.
        source = " ".join(inspect.getsource(spawn_teammate.main).split())
        self.assertIn("run_cwd = ( cwd if args.in_place else create_worktree(", source)
        self.assertNotIn(
            "if not args.in_place",
            source,
            "in-place exclusion must stay structural, not become a guard",
        )


if __name__ == "__main__":
    unittest.main()
