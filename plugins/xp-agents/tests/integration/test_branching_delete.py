#!/usr/bin/env python3
"""Tests for branching.delete_branch's force-delete fallback."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching
from _bases import _PLUGIN_ROOT


def _checkout_and_merge(td: str, target: str, source: str) -> None:
    subprocess.run(["git", "checkout", target], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "merge", "--no-ff", source, "-m", f"merge {source}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_bf.GIT_ENV,
    )


def _setup_merged_branch(td: str, branch: str, *, diverge: bool = False) -> str:
    """Init repo, branch off main with one commit, optionally diverge the
    tracking ref, then merge into main. Returns the main branch name."""
    _bf.init_repo(td)
    if diverge:
        _bf.add_bare_remote(td)
    main = _bf.get_current_branch(td)
    _bf.make_commit(td, branch, f"{branch.replace('/', '-')}.txt", "x", f"add {branch}")
    if diverge:
        _bf.diverge_tracking_ref(td, branch)
    _checkout_and_merge(td, main, branch)
    return main


class TestDeleteBranchBackwardCompatible(unittest.TestCase):
    def test_safe_path_unchanged_when_no_merge_target(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "feature-clean")
            self.assertTrue(branching.delete_branch(td, "feature-clean"))
            self.assertFalse(_bf.branch_exists(td, "feature-clean"))

    def test_returns_false_when_d_refuses_and_no_merge_target(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-001-diverged", diverge=True)
            self.assertFalse(branching.delete_branch(td, "paul/story-001-diverged"))
            self.assertTrue(_bf.branch_exists(td, "paul/story-001-diverged"))


class TestDeleteBranchForceFallback(unittest.TestCase):
    def test_falls_back_to_force_when_merged_to_target(self):
        with tempfile.TemporaryDirectory() as td:
            main = _setup_merged_branch(td, "paul/story-002-merged", diverge=True)
            self.assertTrue(
                branching.delete_branch(td, "paul/story-002-merged", merge_target=main)
            )
            self.assertFalse(_bf.branch_exists(td, "paul/story-002-merged"))


class TestDeleteBranchForceSafety(unittest.TestCase):
    def test_refuses_force_when_not_merged_to_target(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "paul/story-003-unmerged", "u.txt", "x", "add u")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            self.assertFalse(
                branching.delete_branch(
                    td, "paul/story-003-unmerged", merge_target=main
                )
            )
            self.assertTrue(_bf.branch_exists(td, "paul/story-003-unmerged"))


class TestDeleteBranchForceNeedsASurvivingRef(unittest.TestCase):
    """The `-D` proof is "the branch is an ancestor of the target, so every
    commit on it is reachable from the target". That is only worth something
    when the target is a DIFFERENT ref that OUTLIVES the delete. Two inputs make
    it vacuous, and both force-deleted unmerged work before this guard:

    - target IS the branch (`git merge-base --is-ancestor X X` exits 0 — a
      commit is its own ancestor). Reachable via the CLI's DEFAULT: the merge
      target resolves to the recorded plan branch, so `delete --branch <plan>`
      proves the plan branch against itself.
    - target is a bare SHA. Ancestry holds, but a SHA is not a ref — after the
      branch ref is gone nothing points at the work.
    """

    def _unmerged_branch(self, td: str, branch: str) -> None:
        _bf.init_repo(td)
        main = _bf.get_current_branch(td)
        _bf.make_commit(td, branch, "u.txt", "x", "add u")
        subprocess.run(
            ["git", "checkout", main], cwd=td, capture_output=True, check=True
        )

    def test_refuses_force_when_target_is_the_branch_itself(self):
        with tempfile.TemporaryDirectory() as td:
            self._unmerged_branch(td, "paul/plan-selftarget")
            self.assertFalse(
                branching.delete_branch(
                    td, "paul/plan-selftarget", merge_target="paul/plan-selftarget"
                )
            )
            self.assertTrue(_bf.branch_exists(td, "paul/plan-selftarget"))

    def test_refuses_force_when_target_is_a_bare_sha(self):
        with tempfile.TemporaryDirectory() as td:
            self._unmerged_branch(td, "paul/story-005-sha")
            tip = subprocess.run(
                ["git", "rev-parse", "paul/story-005-sha"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertFalse(
                branching.delete_branch(td, "paul/story-005-sha", merge_target=tip)
            )
            self.assertTrue(_bf.branch_exists(td, "paul/story-005-sha"))


class TestDeleteBranchMissing(unittest.TestCase):
    def test_returns_false_when_branch_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            self.assertFalse(
                branching.delete_branch(td, "no-such-branch", merge_target=main)
            )


class TestDeleteCLIPassesMergeTarget(unittest.TestCase):
    """Concern a627887a7dec: `branching_cli delete` never passed a merge_target,
    so delete_branch's ancestry-proven `-D` fallback could NEVER engage from the
    CLI — and it wrote nothing to stderr.

    xp-kickoff/SKILL.md says "merge ... then delete": it merges, then calls
    delete WITHOUT telling it what the target was. `git branch -d` refuses when
    a branch's tip differs from its upstream tracking ref even though it is
    fully merged — the case worktree teammates hit at every close. So the user
    answers "merge", gets the merge, and then a SILENT exit 1.

    Defaulting the target destroys nothing so long as `-D` fires only when the
    branch is an ancestor of a DIFFERENT ref that SURVIVES the delete — then
    every commit on it stays reachable and only the name is lost.
    ``TestDeleteBranchForceNeedsASurvivingRef`` guards the other half of that
    invariant; the default is the right target by construction, because
    kickoff's merge-branch resolves its target the same way, so the merge leg
    and the ancestry proof cannot disagree.
    """

    def _delete(self, td: str, branch: str, *flags: str, smm_dir: str | None = None):
        cli = str(_PLUGIN_ROOT / "scripts" / "branching.py")
        return subprocess.run(
            [
                *[sys.executable, cli, "--smm-dir", smm_dir or td, "delete"],
                *["--cwd", td, "--branch", branch, *flags],
            ],
            capture_output=True,
            text=True,
            env=_bf.GIT_ENV,
        )

    def test_merged_but_diverged_from_upstream_now_deletes(self):
        """The teammate-close case. Was a silent exit 1; the branch is fully
        merged, so `-D` is provably safe."""
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-002-merged", diverge=True)
            result = self._delete(td, "paul/story-002-merged")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "paul/story-002-merged"))

    def test_commits_ahead_of_target_still_refused_and_no_longer_silent(self):
        """Pins BOTH halves: no destroy, AND no silence. A branch with commits
        ahead is not an ancestor, so `-D` never fires and the delete still
        fails — but it now says why."""
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            _bf.make_commit(td, "paul/story-003-unmerged", "u.txt", "x", "add u")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            result = self._delete(td, "paul/story-003-unmerged")
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stderr.strip(), "a silent exit 1 IS the bug")
            self.assertIn("paul/story-003-unmerged", result.stderr)
            self.assertTrue(
                _bf.branch_exists(td, "paul/story-003-unmerged"),
                "unmerged work must survive",
            )

    def test_explicit_target_is_honored(self):
        with tempfile.TemporaryDirectory() as td:
            main = _setup_merged_branch(td, "paul/story-004-merged", diverge=True)
            result = self._delete(td, "paul/story-004-merged", "--target", main)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, "paul/story-004-merged"))


class TestDeleteCLIRefusalIsHonest(unittest.TestCase):
    """Every refusal the CLI prints must be TRUE of the state it saw.

    The refusal reason used to be a single hardcoded "it is not merged into
    <target>" — asserted, never checked. It is a lie for a branch that does not
    exist, for a target that does not exist locally (no ancestry was ever
    proven), and for a target that resolved to the branch itself. Each arm here
    pins a state where the old sentence was false.
    """

    def _delete(self, td: str, branch: str, *flags: str, smm_dir: str | None = None):
        cli = str(_PLUGIN_ROOT / "scripts" / "branching.py")
        return subprocess.run(
            [
                *[sys.executable, cli, "--smm-dir", smm_dir or td, "delete"],
                *["--cwd", td, "--branch", branch, *flags],
            ],
            capture_output=True,
            text=True,
            env=_bf.GIT_ENV,
        )

    def test_default_target_resolving_to_the_branch_itself_refuses(self):
        """The destructive default. get_merge_target returns the RECORDED PLAN
        BRANCH when one exists, so `delete --branch <that plan branch>` proved
        it an ancestor of ITSELF and force-deleted unmerged plan work."""
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            main = _bf.get_current_branch(td)
            plan_branch = "paul/plan-rework"
            _bf.make_commit(td, plan_branch, "p.txt", "x", "plan work")
            subprocess.run(
                ["git", "checkout", main], cwd=td, capture_output=True, check=True
            )
            smm = Path(td) / "smm"
            smm.mkdir()
            _bf.seed_plan(smm, branch=plan_branch)

            result = self._delete(td, plan_branch, smm_dir=str(smm))

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertTrue(
                _bf.branch_exists(td, plan_branch), "unmerged plan work must survive"
            )
            self.assertIn("itself", result.stderr)

    def test_worktree_held_branch_reaches_the_refusal_and_survives(self):
        """A held branch is NOT caught earlier: `-d` refuses ("checked out at"),
        the branch IS merged so the ancestry proof passes, and `-D` refuses too
        (git will not delete a checked-out branch) — so it lands in the refusal
        with delete_branch False. Kickoff must not borrow close_common's return-0
        escape hatch here: nothing in kickoff removes the worktree afterwards."""
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-007-held")
            wt = str(Path(td) / "wt")
            subprocess.run(
                ["git", "worktree", "add", wt, "paul/story-007-held"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )
            result = self._delete(td, "paul/story-007-held")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checked out in a worktree", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "paul/story-007-held"))

    def test_missing_branch_is_not_reported_as_unmerged(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = self._delete(td, "paul/story-404-gone")
            self.assertEqual(result.returncode, 1)
            self.assertIn("paul/story-404-gone", result.stderr)
            self.assertNotIn("not merged", result.stderr)

    def test_unresolvable_target_is_not_reported_as_unmerged(self):
        """`-d` refuses (diverged tracking ref) and the target names nothing, so
        no ancestry was ever proven either way. Claiming "not merged" invents a
        fact; the honest answer is that the target does not resolve."""
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-006-merged", diverge=True)
            result = self._delete(
                td, "paul/story-006-merged", "--target", "no-such-target"
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("no-such-target", result.stderr)
            self.assertNotIn("not merged", result.stderr)


if __name__ == "__main__":
    unittest.main()
