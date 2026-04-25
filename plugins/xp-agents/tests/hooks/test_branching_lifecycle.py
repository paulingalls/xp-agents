#!/usr/bin/env python3
"""Tests for branching.py — git-operation lifecycle tests.

Covers: is_worktree_clean, branch_exists, create_story_branch,
merge_story_branch, delete_branch, CLI (E2E).

Split from test_branching.py — pure-function unit tests remain there.
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

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context


def _make_feature_commit(td: str, filename: str = "feature.txt") -> None:
    (Path(td) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )


class TestIsWorktreeClean(unittest.TestCase):
    def test_clean_repo(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertTrue(branching.is_worktree_clean(td))

    def test_dirty_repo(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            self.assertFalse(branching.is_worktree_clean(td))


class TestBranchExists(unittest.TestCase):
    def test_existing_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "feature-x"], cwd=td, capture_output=True, check=True
            )
            self.assertTrue(branching.branch_exists(td, "feature-x"))

    def test_nonexistent_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertFalse(branching.branch_exists(td, "no-such-branch"))


class TestCreateStoryBranch(unittest.TestCase):
    def test_creates_and_checks_out_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "branch-lifecycle", smm_dir
                )

            self.assertEqual(result, "paul/story-001-branch-lifecycle")
            self.assertEqual(_get_current_branch(td), "paul/story-001-branch-lifecycle")

    def test_skips_at_stage_zero(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_skips_when_no_system_context(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_resume_existing_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/story-001-resume"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "resume", smm_dir
                )

            self.assertEqual(result, "paul/story-001-resume")
            self.assertEqual(_get_current_branch(td), "paul/story-001-resume")

    def test_raises_when_dirty(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "dirty", smm_dir)

    def test_exits_when_existing_checkout_fails(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            fail_result = subprocess.CompletedProcess(
                ["git", "checkout"], 1, "", "error: conflict"
            )

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.branch_exists", return_value=True),
                patch("branching._git", return_value=fail_result),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "conflict", smm_dir)


class TestMergeStoryBranch(unittest.TestCase):
    def test_merge_commit_created(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-test"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td)

            branching.merge_story_branch(td, "paul/story-001-test", target=main_branch)

            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("paul/story-001-test", merges.stdout)

    def test_merge_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-002-hist"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            for i in range(3):
                _make_feature_commit(td, f"file{i}.txt")

            branching.merge_story_branch(td, "paul/story-002-hist", target=main_branch)

            log = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            for i in range(3):
                self.assertIn(f"file{i}.txt", log.stdout)


class TestMergeSprintBranch(unittest.TestCase):
    def test_merges_into_target(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-027-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td)

            branching.merge_sprint_branch(
                td, "paul/sprint-027-feat", target=main_branch
            )

            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("paul/sprint-027-feat", merges.stdout)
            self.assertEqual(_get_current_branch(td), main_branch)

    def test_exits_on_merge_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            (Path(td) / "shared.txt").write_text("from-main")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=td, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "main side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-027-conflict", "HEAD~1"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            (Path(td) / "shared.txt").write_text("from-sprint")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=td, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "sprint side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            with self.assertRaises(SystemExit):
                branching.merge_sprint_branch(
                    td, "paul/sprint-027-conflict", target=main_branch
                )


class TestDeleteBranch(unittest.TestCase):
    def test_deletes_merged_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-del"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "f.txt")

            subprocess.run(
                ["git", "checkout", main_branch],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "merge", "--no-ff", "paul/story-001-del", "-m", "merge"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            result = branching.delete_branch(td, "paul/story-001-del")
            self.assertTrue(result)
            self.assertFalse(branching.branch_exists(td, "paul/story-001-del"))


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
                    "merge",
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

    def test_merge_story_branch_signature_has_no_target_default(self):
        import inspect

        sig = inspect.signature(branching.merge_story_branch)
        self.assertIs(
            sig.parameters["target"].default,
            inspect.Parameter.empty,
            "merge_story_branch must NOT default target to 'main'",
        )

    def test_merge_sprint_branch_signature_has_no_target_default(self):
        import inspect

        sig = inspect.signature(branching.merge_sprint_branch)
        self.assertIs(
            sig.parameters["target"].default,
            inspect.Parameter.empty,
            "merge_sprint_branch must NOT default target to 'main'",
        )

    def test_cli_argparse_target_default_is_none(self):
        """Argparse --target on merge / merge-sprint defaults to None.

        Guards the CLI surface against re-introduction of `default="main"`
        which would bypass get_merge_target and silently misroute Stage-3
        merges. Captures the parsed Namespace via a stub-out.
        """
        captured: dict[str, object] = {}

        def _capture(args):
            captured.setdefault("ns", args)
            return 0

        for cmd in ("merge", "merge-sprint"):
            with self.subTest(cmd=cmd):
                captured.clear()
                attr = "_cmd_merge" if cmd == "merge" else "_cmd_merge_sprint"
                argv = [
                    "branching.py",
                    "--smm-dir",
                    "/tmp",
                    cmd,
                    "--cwd",
                    ".",
                    "--branch",
                    "x",
                ]
                with (
                    patch.object(branching, attr, _capture),
                    patch.object(sys, "argv", argv),
                ):
                    branching.main()
                self.assertIsNone(captured["ns"].target)

    def test_cli_merge_sprint_routes_through_get_merge_target_when_omitted(self):
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
            # Invoke merge-sprint WITHOUT --target. Must route through
            # get_merge_target which returns the recorded plan branch.
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "merge-sprint",
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


class TestRecordedPlanBranchPrefixFallback(unittest.TestCase):
    """sprint-032 C1b: _recorded_plan_branch falls back via prefix match.

    Constraints pillar: 'lookups use stored name with prefix-fallback to
    handle slug drift'. If the plan branch was renamed locally (e.g. user
    appended a -v2 suffix or shortened the slug), exact branch_exists
    misses and get_merge_target silently routes to primary. Mirror the
    pattern get_story_base_branch already uses for sprint branches.
    """

    def test_falls_back_to_prefix_match_when_exact_missing(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Create a branch with a drifted slug (no exact match).
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-feat-v2"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            with patch("sys.stderr") as fake_err:
                result = branching._recorded_plan_branch(td, smm_dir)
            self.assertEqual(result, "paul/plan-feat-v2")
            # Communication: the drift fallback must be visible.
            printed = "".join(
                str(call.args[0]) for call in fake_err.write.call_args_list if call.args
            )
            self.assertIn("paul/plan-feat", printed)
            self.assertIn("paul/plan-feat-v2", printed)

    def test_anchored_glob_excludes_substring_extensions(self):
        """`<branch>-*` must not match `<branch>extra` (e.g. featured)."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Substring-extension branch: 'feat' is a prefix but no -separator.
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-featured"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertIsNone(result)

    def test_returns_none_when_no_prefix_match(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-missing")
            # Different prefix entirely — no match.
            subprocess.run(
                ["git", "checkout", "-b", "paul/other-branch"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertIsNone(result)

    def test_exact_match_preferred_over_prefix(self):
        """When the recorded branch exists exactly, return it (no scan)."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Create both an exact match AND a longer-prefix sibling.
            subprocess.run(
                ["git", "branch", "paul/plan-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "branch", "paul/plan-feat-v2"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertEqual(result, "paul/plan-feat")


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
                branching.merge_sprint_branch(
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
