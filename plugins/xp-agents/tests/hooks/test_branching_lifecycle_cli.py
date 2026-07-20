#!/usr/bin/env python3
"""Tests for branching.py and branching_cli.py — CLI dispatch (E2E),
explicit merge-target enforcement, and merge-failure messaging.

Covers: full create -> merge -> delete CLI cycle, the `stage` subcommand,
merge_branch's no-default target signature (sprint-032 C1a), and
merge-conflict error-message content (sprint-032 C1c).

Split from test_branching_lifecycle.py — commits-ahead, worktree-clean,
branch-exists, and direct merge_branch/delete_branch tests remain there.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching
import branching_cli

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_make_feature_commit = _bf.append_commit


class TestCLI(unittest.TestCase):
    """E2E: full create → merge → delete cycle via CLI subprocess."""

    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )

            # Create story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "create",
                    "--cwd",
                    td,
                    "--story",
                    "story-001",
                    "--slug",
                    "lifecycle-test",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/story-001-lifecycle-test", r.stdout)

            _make_feature_commit(td)

            # Merge story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "merge-branch",
                    "--cwd",
                    td,
                    "--branch",
                    "test/story-001-lifecycle-test",
                    "--target",
                    main_branch,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            # Delete story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "delete",
                    "--cwd",
                    td,
                    "--branch",
                    "test/story-001-lifecycle-test",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            # Verify merge commit exists and branch is gone
            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("story-001-lifecycle-test", merges.stdout)

            branches = subprocess.run(
                ["git", "branch"], cwd=td, capture_output=True, text=True
            )
            self.assertNotIn("story-001-lifecycle-test", branches.stdout)

    def test_stage_command(self):
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )
            r = subprocess.run(
                [sys.executable, script, "--smm-dir", str(smm_dir), "stage"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("2", r.stdout)


class TestRequireExplicitMergeTarget(unittest.TestCase):
    """sprint-032 C1a: drop default target='main' from merge_*_branch.

    Stage-3 plan branches merge to integration_branch (per Constraints
    pillar). A 'main' default makes Stage-3 callers silently misroute.
    Force callers to be explicit.
    """

    def test_merge_branch_signature_has_no_target_default(self):
        import inspect

        sig = inspect.signature(branching.merge_branch)
        self.assertIs(
            sig.parameters["target"].default,
            inspect.Parameter.empty,
            "merge_branch must NOT default target to 'main'",
        )

    def test_cli_argparse_target_default_is_none(self):
        """Argparse --target on merge / merge-branch defaults to None.

        Guards the CLI surface against re-introduction of `default="main"`
        which would bypass get_merge_target and silently misroute Stage-3
        merges. Captures the parsed Namespace via a stub-out.
        """
        captured: dict[str, object] = {}

        def _capture(args):
            captured.setdefault("ns", args)
            return 0

        argv = [
            "branching.py",
            "--smm-dir",
            "/tmp",
            "merge-branch",
            "--cwd",
            ".",
            "--branch",
            "x",
        ]
        with (
            patch.object(branching_cli, "_cmd_merge_branch", _capture),
            patch.object(sys, "argv", argv),
        ):
            branching_cli.main()
        self.assertIsNone(captured["ns"].target)  # type: ignore[attr-defined]

    def test_cli_merge_branch_routes_through_get_merge_target_when_omitted(self):
        """CLI without --target uses get_merge_target (not literal 'main')."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            primary = _get_current_branch(td)

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")

            # Create plan branch and a sprint-feature branch off it.
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "plan-base.txt")
            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-099-x"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "sprint-feat.txt")

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )
            # Invoke merge-branch WITHOUT --target. Must route through
            # get_merge_target which returns the recorded plan branch.
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "merge-branch",
                    "--cwd",
                    td,
                    "--branch",
                    "paul/sprint-099-x",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            # HEAD should now be on the plan branch, not on primary.
            self.assertEqual(_get_current_branch(td), "paul/plan-feat")
            self.assertNotEqual(_get_current_branch(td), primary)


class TestMergeFailureMessage(unittest.TestCase):
    """sprint-032 C1c: _merge_into_target failure print includes context.

    Honesty: git merge writes conflict details to stdout (not stderr).
    The previous error print swallowed stdout AND omitted the source/
    target branch names, leaving operators with a blank 'Merge failed:'
    line and no clue which merge went wrong.
    """

    def test_failure_message_includes_stdout_and_branch_names(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)
            (Path(td) / "shared.txt").write_text("from-main")
            subprocess.run(
                ["git", "add", "shared.txt"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "main side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )
            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-099-conflict", "HEAD~1"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            (Path(td) / "shared.txt").write_text("from-sprint")
            subprocess.run(
                ["git", "add", "shared.txt"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "sprint side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            with patch("sys.stderr") as fake_err, self.assertRaises(SystemExit):
                branching.merge_branch(
                    td, "paul/sprint-099-conflict", target=main_branch
                )

            printed = "".join(
                str(call.args[0]) for call in fake_err.write.call_args_list if call.args
            )
            # Source and target branch names
            self.assertIn("paul/sprint-099-conflict", printed)
            self.assertIn(main_branch, printed)
            # git's actual conflict marker (stdout) — proves stdout is included
            self.assertIn("CONFLICT", printed)


if __name__ == "__main__":
    unittest.main()
