#!/usr/bin/env python3
"""`worktree_differential` — run one declared command in the primary checkout
and in a bare throwaway worktree, and compare the two TRUE exit codes.

The instrument spike-005 concluded is required: a bootstrap candidate's own
exit code proves nothing (both measured candidates exited 0 and one fixed
nothing), so only re-measuring the differential separates them.

Every declared command in this suite must be independently harmless. The
suite-wide spawn guard (installed by importing `conftest`) patches `Popen` only
for `argv[0] == "claude"`, and these commands run through `/bin/sh` with
`shell=True` — straight past it. So: `test -f`, `sleep`, `sh -c 'exit N'`, and
nothing that writes outside the temp repo.

`_IntegrationTestCase.tearDown` already sweeps `worktree-`-prefixed worktrees
out of the temp repo, which is why the throwaway carries that prefix (while
staying out of the `worktree-story-` teammate namespace). The removal tests
below therefore assert the PRODUCTION `finally` ran, not that cleanup exists.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import worktree_differential
from conftest import _IntegrationTestCase


class TestUndifferentiableRefusal(unittest.TestCase):
    """Step 1: refuse a command whose exit code means nothing, loudly.

    `pytest | tee log` reports the PIPE's exit status, so its two legs would be
    compared on a number unrelated to either checkout — the method failure that
    nearly made spike-005 itself report a red control run as green.
    """

    def test_a_test_runner_pipeline_is_refused(self) -> None:
        reason = worktree_differential.undifferentiable_reason(
            "pytest -n auto | tee log"
        )
        self.assertIsNotNone(reason)

    def test_a_non_test_pipeline_is_refused_too(self) -> None:
        """The decisive case. The checkout-VARIANT artifact spike-005 measured
        was a TYPECHECK — a command with no test runner in it — so a guard that
        only catches runner pipelines is inert for exactly the command that
        motivated the feature."""
        for command in (
            "tsc --noEmit | tee log",
            "make build | tee log",
            "cargo build | tee log",
            "go vet ./... | tee log",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(
                    worktree_differential.undifferentiable_reason(command)
                )

    def test_the_reason_names_the_command_and_the_problem(self) -> None:
        """A refusal the operator cannot act on is a silent failure with extra
        steps: it has to say which command and why."""
        reason = worktree_differential.undifferentiable_reason("tsc --noEmit | tee log")
        # `or ""` rather than an assertIsNotNone crutch: an empty string fails
        # the two assertions below just as a None would.
        reason = reason or ""
        self.assertIn("tsc --noEmit | tee log", reason)
        self.assertIn("exit", reason.lower())

    def test_a_blank_command_is_refused(self) -> None:
        """There is nothing to measure, and the structural predicate answers
        True for it vacuously — so this refusal is `differential`'s own."""
        for command in ("", "   ", "\n"):
            with self.subTest(command=repr(command)):
                self.assertIsNotNone(
                    worktree_differential.undifferentiable_reason(command)
                )

    def test_ordinary_commands_are_differentiable(self) -> None:
        for command in (
            "pytest -n auto",
            "tsc --noEmit",
            "cd app && cargo build",
            "make test\n",
            "sh -c 'exit 3'",
        ):
            with self.subTest(command=command):
                self.assertIsNone(
                    worktree_differential.undifferentiable_reason(command)
                )


class _DifferentialTestCase(_IntegrationTestCase):
    """A temp git repo plus helpers for reading back what the run left behind."""

    def run_differential(self, command: str, **kwargs) -> dict:
        return worktree_differential.differential(
            command, str(self.tmpdir), self.smm_dir, **kwargs
        )

    def add_untracked_probe(self, name: str = "probe.txt") -> None:
        """A file present in the primary and ABSENT from any fresh worktree.

        The synthetic gap this repo cannot supply on its own: `git worktree add`
        materializes only TRACKED files, so an untracked (or gitignored) probe
        is exactly the shape of the real gitignored-state gap. Excluded as well
        as untracked so it cannot dirty a sibling test's `git status`.
        """
        exclude = self.tmpdir / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(f"{name}\n")
        (self.tmpdir / name).write_text("present in the primary only\n")

    def live_throwaways(self) -> list[Path]:
        """Any throwaway worktree directory still on disk."""
        base = self.smm_dir.parent / "worktrees"
        if not base.is_dir():
            return []
        return [d for d in base.iterdir() if d.name.startswith("worktree-diff-")]

    def registered_worktrees(self) -> list[str]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        return [
            line.split(" ", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("worktree ")
        ]

    def assertNoThrowawayLeft(self) -> None:
        self.assertEqual(self.live_throwaways(), [])
        leaked = [p for p in self.registered_worktrees() if "worktree-diff-" in p]
        self.assertEqual(leaked, [], "a throwaway is still in the git registry")


class TestSubdirectoryCwdIsRefused(_DifferentialTestCase):
    """A *cwd* below the checkout root compares two POSITIONS, not two checkouts.

    The worktree leg always runs at the throwaway's ROOT. Measured on a tree
    with every file TRACKED and committed — where no provisioning gap is
    possible — a subdirectory cwd reported gap 0 vs 2 on "no rule to make
    target". Story-004 turns a gap into a question for a human, so this would
    manufacture a false question with a misleading diagnostic.
    """

    def test_subdirectory_cwd_is_refused_not_measured(self) -> None:
        sub = self.tmpdir / "app"
        sub.mkdir()
        (sub / "marker.txt").write_text("tracked\n")
        subprocess.run(["git", "add", "-A"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "commit", "-m", "add app/"], cwd=self.tmpdir, check=True)

        result = worktree_differential.differential(
            "test -f marker.txt", str(sub), self.smm_dir
        )

        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_REFUSED)
        self.assertIn("subdirectory", result["reason"])
        self.assertNoThrowawayLeft()

    def test_a_non_git_cwd_is_refused(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)

        result = worktree_differential.differential("true", str(outside), self.smm_dir)

        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_REFUSED)
        self.assertIn("not a git checkout", result["reason"])


class TestTimeoutNamesItsLeg(_DifferentialTestCase):
    """Reporting a hung PRIMARY's output under `worktree_output` points the
    operator at the wrong checkout."""

    def test_a_hung_primary_leg_is_named_and_reported_as_primary(self) -> None:
        # `&&`, not `;` — a `;` discards the exit status, so the structural
        # guard refuses the command before either leg runs.
        result = self.run_differential("echo hanging-here >&2 && sleep 30", timeout=1)

        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_ERROR)
        self.assertIn("primary leg timed out", result["reason"])
        self.assertIn("hanging-here", result["primary_output"])
        self.assertEqual(
            result["worktree_output"],
            "",
            "the worktree leg never ran; attributing the primary's output to it "
            "sends the operator to the wrong checkout",
        )
        self.assertNoThrowawayLeft()


class TestDegradedPlacementIsReported(_DifferentialTestCase):
    """`worktree_path` falls back to IN-REPO placement when the out-of-repo base
    is unresolvable. A module walk-up from there reaches the primary's installed
    dependencies, so a real gap can read as no_gap.

    Every other caveat describes a false POSITIVE, costing a spurious question.
    This one is a false NEGATIVE — the direction the module's own doctrine says
    must never ship silently.
    """

    def test_in_repo_placement_adds_a_caveat(self) -> None:
        def in_repo(name: str, cwd: str) -> Path:
            return Path(cwd) / ".claude" / "worktrees" / name

        with patch.object(
            worktree_differential.worktree, "worktree_path", side_effect=in_repo
        ):
            result = self.run_differential("true")

        joined = " ".join(result["caveats"])
        self.assertIn("DEGRADED PLACEMENT", joined)
        self.assertIn("inconclusive", joined)
        # The intrinsic caveats must survive alongside the run-specific one.
        self.assertIn("PATH SENSITIVITY", joined)

    def test_out_of_repo_placement_adds_no_caveat(self) -> None:
        """The other half of the pair: without it, a test asserting the caveat's
        presence would also pass against an implementation that always adds it."""
        result = self.run_differential("true")

        self.assertNotIn("DEGRADED PLACEMENT", " ".join(result["caveats"]))


class TestTwoLegCompare(_DifferentialTestCase):
    """Steps 2-3: run both legs identically, compare the TRUE exit codes."""

    def test_a_gap_reports_both_exit_codes(self) -> None:
        """AC1. `test -f probe.txt` passes in the primary and fails in a bare
        worktree, because the probe is untracked."""
        self.add_untracked_probe()
        result = self.run_differential("test -f probe.txt")
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_GAP)
        self.assertEqual(result["primary_exit"], 0)
        self.assertNotEqual(result["worktree_exit"], 0)

    def test_no_gap_when_both_checkouts_agree(self) -> None:
        """AC2. README is TRACKED, so it is materialized in the worktree too —
        path-insensitive by construction."""
        result = self.run_differential("test -f README")
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_NO_GAP)
        self.assertEqual(result["primary_exit"], 0)
        self.assertEqual(result["worktree_exit"], 0)

    def test_the_exit_code_is_the_commands_own_not_a_pipelines(self) -> None:
        """AC4. An implementation that appends `| tail` to capture output gets
        tail's 0 back and fails here — the spike's own method failure."""
        result = self.run_differential("sh -c 'exit 3'")
        self.assertEqual(result["primary_exit"], 3)
        self.assertEqual(result["worktree_exit"], 3)
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_NO_GAP)

    def test_an_undifferentiable_command_is_refused_not_measured(self) -> None:
        """Refused BEFORE either leg runs: there is nothing to compare, so
        spending two runs to produce a meaningless number is the wrong trade."""
        with patch.object(
            worktree_differential._subprocess_env, "run_in_new_process_group"
        ) as run:
            result = self.run_differential("tsc --noEmit | tee log")
        run.assert_not_called()
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_REFUSED)
        self.assertIn("tsc --noEmit | tee log", result["reason"])

    def test_both_legs_share_one_env_and_one_timeout(self) -> None:
        """The two legs must differ by their CHECKOUT and nothing else. A
        different env (or a `None` timeout on one) measures the wrong variable.
        """
        with patch.object(
            worktree_differential._subprocess_env,
            "run_in_new_process_group",
            wraps=worktree_differential._subprocess_env.run_in_new_process_group,
        ) as run:
            self.run_differential("test -f README")
        self.assertEqual(run.call_count, 2)
        primary, worktree = run.call_args_list
        self.assertEqual(primary.kwargs["env"], worktree.kwargs["env"])
        self.assertEqual(primary.kwargs["env"]["SMM_DIR"], str(self.smm_dir.resolve()))
        self.assertEqual(primary.kwargs["timeout"], worktree.kwargs["timeout"])
        self.assertNotEqual(primary.kwargs["cwd"], worktree.kwargs["cwd"])

    def test_the_default_timeout_is_a_positive_int(self) -> None:
        """`run_in_new_process_group` hands `timeout` to `communicate()`, where
        None blocks forever — so a hung declared command would hang the tool,
        the exact hazard the process-group work exists to close."""
        with patch.object(
            worktree_differential._subprocess_env,
            "run_in_new_process_group",
            wraps=worktree_differential._subprocess_env.run_in_new_process_group,
        ) as run:
            self.run_differential("test -f README")
            self.run_differential("test -f README", timeout=0)
        for call in run.call_args_list:
            timeout = call.kwargs["timeout"]
            self.assertIsInstance(timeout, int)
            self.assertGreater(timeout, 0)

    def test_the_report_names_both_intrinsic_false_positives(self) -> None:
        """The result is a candidate signal, never a verdict: a worktree always
        sits at a different path (spike §6), and it is created at HEAD while the
        primary leg runs against the WORKING TREE. Story-004 asks a human, so
        the caveats have to travel with the number."""
        self.add_untracked_probe()
        result = self.run_differential("test -f probe.txt")
        caveats = " ".join(result["caveats"]).lower()
        self.assertIn("path", caveats)
        self.assertIn("head", caveats)


class TestThrowawayAlwaysRemoved(_DifferentialTestCase):
    """AC3, and the acceptance criterion with no precedent in shipped code:
    nothing else here wraps worktree create/remove in `try/finally`."""

    def test_removed_after_a_crash(self) -> None:
        with (
            patch.object(
                worktree_differential._subprocess_env,
                "run_in_new_process_group",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.run_differential("test -f README")
        self.assertNoThrowawayLeft()

    def test_removed_after_a_timeout_and_the_timeout_is_reported(self) -> None:
        """A one-leg timeout has no `returncode` to compare, so it is an ERROR,
        not a gap: a slow-but-healthy command must never be reported as needing
        a bootstrap no bootstrap could supply."""
        result = self.run_differential("sleep 30", timeout=1)
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_ERROR)
        self.assertIn("timed out", result["reason"])
        self.assertNoThrowawayLeft()

    def test_removed_after_a_clean_run(self) -> None:
        self.run_differential("test -f README")
        self.assertNoThrowawayLeft()

    def test_a_stranded_throwaway_does_not_block_the_next_run(self) -> None:
        """A crash between `add` and the `finally` strands the directory. A
        fixed name would then fail every subsequent run, so the name is
        per-run unique AND a pre-existing path is cleared rather than fatal."""
        base = self.smm_dir.parent / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        with patch.object(
            worktree_differential, "_throwaway_name", return_value="worktree-diff-fixed"
        ):
            stranded = base / "worktree-diff-fixed"
            stranded.mkdir()
            (stranded / "debris").write_text("left by a crashed run\n")
            result = self.run_differential("test -f README")
        self.assertEqual(result["outcome"], worktree_differential.OUTCOME_NO_GAP)
        self.assertNoThrowawayLeft()

    def test_the_throwaway_is_never_in_the_teammate_namespace(self) -> None:
        """`worktree_path` resolves into the same directory that holds LIVE
        teammate worktrees, and removal is `--force`. A name collision destroys
        a running teammate's uncommitted work."""
        names = {worktree_differential._throwaway_name() for _ in range(5)}
        self.assertEqual(len(names), 5, "the name must be unique per run")
        for name in names:
            self.assertFalse(name.startswith("worktree-story-"))
            self.assertTrue(name.startswith("worktree-diff-"))


if __name__ == "__main__":
    unittest.main()
