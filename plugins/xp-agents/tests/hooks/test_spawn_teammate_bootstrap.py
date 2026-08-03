#!/usr/bin/env python3
"""Tests for spawn_teammate's worktree bootstrap runner.

`git worktree add` materializes only tracked files, so every gitignored
artifact a project needs is absent from a fresh teammate worktree —
spike-005 measured the dominant effect as a loud false-RED (TS2882, exit 2),
with a rarer false-GREEN also possible. A project can declare
`stack.worktree_bootstrap`; spawn runs it in the new worktree before the agent
takes its first turn.

Every test here asserts the command's EFFECT (a file the command wrote,
inside the worktree), never merely that a runner was called: a call-count
assertion passes against an implementation that never runs anything.

The suite-wide spawn guard does NOT cover this file. It patches
subprocess.Popen to block argv[0] == "claude", but a shell=True bootstrap
runs /bin/sh, which the guard lets through. Every command declared below is
therefore deliberately harmless (writes a marker file, or exits non-zero).

Split at 500 lines. The child env a spawned teammate receives is in
test_teammate_child_env.py, and the recorded-rationale prose assertions in
test_bootstrap_rationale_prose.py.
"""

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

# Imported for its SIDE EFFECT as much as any symbol: conftest installs the
# suite-wide backstop that makes launching the real `claude` binary impossible
# (see test_no_test_can_spawn_a_real_agent.py, which PINS this import for every
# module that imports spawn_teammate). The rule is structural — importing the
# module that can spawn is the fact that matters, not how main() is reached.
import conftest  # noqa: F401
import spawn_teammate
from _bootstrap_fixtures import _BootstrapTestCase
from _system_context_fixtures import valid_doc, write_doc


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

    def test_bootstrap_failure_message_is_caller_neutral(self):
        # run_bootstrap is now reachable from the platform WorktreeCreate hook
        # (no agent spawn), so its failure message must not be spawn-specific.
        self.declare_bootstrap("echo boom >&2; exit 1")

        with self.assertRaises(SystemExit) as ctx:
            self.spawn()

        message = str(ctx.exception)
        self.assertNotIn("spawn_teammate:", message)
        self.assertNotIn("No agent was started", message)

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


class TestBootstrapKillsProcessGroup(_BootstrapTestCase):
    """A backgrounded, hanging child dies with the process group.

    The sibling assertion for teardown lives in test_worktree_teardown.py.
    Both call the same `_subprocess_env.run_in_new_process_group`, but each
    owns its own call site and its own raise-vs-swallow policy, so shared
    coverage through one caller proves nothing about the other: bootstrap
    could stop passing the timeout, or catch TimeoutExpired differently, and
    the teardown test would stay green.

    Bootstrap's contract here is the LOUD one — it raises SystemExit, where
    teardown swallows — because a half-provisioned worktree must never host
    an agent.
    """

    def test_backgrounded_hanging_child_is_killed_and_bootstrap_raises(self):
        self.declare_bootstrap(
            "echo started > started.txt; "
            "(sleep 30 && echo should-not-appear > leaked.txt) & "
            "wait $!"
        )
        name = "worktree-story-bootstrap"

        with (
            patch.dict(os.environ, {"XP_BOOTSTRAP_TIMEOUT_S": "1"}),
            self.assertRaises(SystemExit) as ctx,
        ):
            self.spawn(name)

        self.assertIn("timed out", str(ctx.exception))

        import worktree

        wt = worktree.worktree_path(name, str(self.tmpdir))
        self.assertTrue((wt / "started.txt").is_file())
        self.assertFalse(
            (wt / "leaked.txt").exists(),
            "the backgrounded grandchild must die with the process group; "
            "reaping only the shell leaves exactly the orphans this "
            "hardening exists to prevent",
        )


class TestBootstrapTimeoutOverride(_BootstrapTestCase):
    """A tunable timeout that can be tuned to a value nothing can satisfy is
    not a tuning knob, it is an off switch for provisioning: `timeout=0` makes
    subprocess.run raise TimeoutExpired before the command has run at all, so
    EVERY spawn dies on a healthy project. Only a POSITIVE override is an
    override; anything else falls back to the default."""

    def _timeout(self, raw: str) -> int:
        import worktree_bootstrap

        with patch.dict(os.environ, {"XP_BOOTSTRAP_TIMEOUT_S": raw}):
            return worktree_bootstrap._bootstrap_timeout()

    def test_positive_override_is_honoured(self):
        self.assertEqual(self._timeout("42"), 42)

    def test_zero_falls_back_to_the_default(self):
        import worktree_bootstrap

        self.assertEqual(
            self._timeout("0"), worktree_bootstrap._DEFAULT_BOOTSTRAP_TIMEOUT_S
        )

    def test_negative_falls_back_to_the_default(self):
        import worktree_bootstrap

        self.assertEqual(
            self._timeout("-1"), worktree_bootstrap._DEFAULT_BOOTSTRAP_TIMEOUT_S
        )

    def test_a_zero_override_still_provisions_the_worktree(self):
        """The effect, not the helper: a healthy project must still bootstrap."""
        self.declare_bootstrap("echo provisioned > generated.txt")

        with patch.dict(os.environ, {"XP_BOOTSTRAP_TIMEOUT_S": "0"}):
            wt_path = self.spawn()

        self.assertTrue((Path(wt_path) / "generated.txt").is_file())


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


class TestTheBootstrapPatchSeam(_BootstrapTestCase):
    """WHICH name a test must patch to intercept create_worktree's bootstrap.

    `from worktree_bootstrap import run_bootstrap` makes the two names share one
    object AT IMPORT, but they are two separate module globals, and patching is
    rebinding: patch the leaf and `create_worktree` still calls the real one.
    That distinction is worth a test rather than a comment, because getting it
    wrong is SILENT and expensive — a test that believes it stubbed the runner
    would execute the project's own declared bootstrap under shell=True, which
    is precisely the harm `smm_dir=None` defaults exist to prevent.
    """

    def test_the_two_names_share_one_object_at_import(self):
        import worktree_bootstrap

        self.assertIs(spawn_teammate.run_bootstrap, worktree_bootstrap.run_bootstrap)

    def test_patching_the_leaf_module_does_NOT_intercept_create_worktree(self):
        import worktree_bootstrap

        self.declare_bootstrap("echo not-stubbed > leaked.txt")

        with patch.object(worktree_bootstrap, "run_bootstrap") as stub:
            wt_path = self.spawn()

        stub.assert_not_called()
        self.assertTrue(
            (Path(wt_path) / "leaked.txt").is_file(),
            "patching the leaf leaves the REAL bootstrap running — the seam is "
            "spawn_teammate.run_bootstrap, and the docstring must say so",
        )

    def test_patching_spawn_teammate_IS_the_working_seam(self):
        self.declare_bootstrap("echo not-stubbed > leaked.txt")

        with patch.object(spawn_teammate, "run_bootstrap") as stub:
            wt_path = self.spawn()

        stub.assert_called_once()
        self.assertFalse(
            (Path(wt_path) / "leaked.txt").exists(),
            "patching the caller's own global must intercept the real command",
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


class TestMainProvisionsTheWorktree(_BootstrapTestCase):
    """The production wiring: a real `spawn_teammate` run must bootstrap.

    Every other test here calls create_worktree DIRECTLY, passing smm_dir by
    hand. main() is the only caller that passes it in production, so nothing
    pinned that it still does: dropping `smm_dir=` from main()'s call makes
    the feature inert in production — no bootstrap ever runs — while the
    whole suite stays green. This drives main() end-to-end and asserts the
    bootstrap's EFFECT, so the wiring cannot rot silently.
    """

    def test_spawning_a_teammate_runs_the_declared_bootstrap(self):
        import contextlib
        import tempfile
        from unittest.mock import patch

        import worktree

        self.declare_bootstrap("echo provisioned > generated.txt")
        name = "worktree-story-bootstrap"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test prompt")
            prompt_path = f.name

        try:
            # main() worktrees off os.getcwd(); the fixture repo is tmpdir.
            with (
                contextlib.chdir(self.tmpdir),
                patch.object(spawn_teammate, "run_with_tee"),
            ):
                spawn_teammate.main(
                    [
                        "--name",
                        name,
                        "--smm-dir",
                        str(self.smm_dir),
                        "--prompt-file",
                        prompt_path,
                    ]
                )
        finally:
            Path(prompt_path).unlink(missing_ok=True)

        artifact = worktree.worktree_path(name, str(self.tmpdir)) / "generated.txt"
        self.assertTrue(
            artifact.is_file(),
            "spawn must thread its SMM dir into create_worktree — without it "
            "no declared bootstrap ever runs and the feature is inert",
        )


if __name__ == "__main__":
    unittest.main()
