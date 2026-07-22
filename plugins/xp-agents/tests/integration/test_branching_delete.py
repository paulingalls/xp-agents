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


def _run_delete(td: str, branch: str, *flags: str, smm_dir: str | None = None):
    """Run `branching.py delete` exactly as xp-kickoff's triage documents it.

    Module-level because three classes drive the same subprocess; keeping it
    per-class produced two byte-identical copies and invited a third.
    ``smm_dir`` defaults to the repo itself — an SMM with no sprint and no
    plan, i.e. the primary-branch fallback.
    """
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


class TestDeleteBranchUpstreamLoophole(unittest.TestCase):
    """`git branch -d` deletes an UNMERGED branch once it is merged to its UPSTREAM.

    Git's rule for `-d` is "fully merged in its upstream branch, OR in HEAD if no
    upstream was set" — upstream WINS when one exists. Every story branch has one:
    /xp-story-close Step 2 runs `close_common.py push` → `git push -u origin
    <branch>`. So after the push, `git branch -d <story>` exits 0 and deletes the
    branch even though nothing was ever merged into the base.

    This is not a tidiness bug. `story_done_gate` reads branch ABSENCE as git-enforced
    PROOF that the merge landed ("every delete path refuses to delete an unmerged
    branch"). The upstream loophole makes that claim false, and a story whose merge
    failed can then be marked `done` — the exact bug the gate exists to stop. So
    `delete_branch` must prove the ancestry ITSELF rather than trusting `-d` to.
    """

    @staticmethod
    def _pushed_unmerged_branch(td: str, branch: str) -> str:
        """A branch pushed with an upstream (Step 2), never merged (Step 7 failed)."""
        _bf.init_repo(td)
        _bf.add_bare_remote(td)
        main = _bf.get_current_branch(td)
        _bf.make_commit(td, branch, "s.txt", "x", "story work")
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=td,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", main], cwd=td, capture_output=True, check=True
        )
        return main

    def test_refuses_to_delete_a_pushed_but_unmerged_branch(self):
        with tempfile.TemporaryDirectory() as td:
            branch = "paul/story-006-pushed"
            main = self._pushed_unmerged_branch(td, branch)

            self.assertFalse(
                branching.is_merged_into(td, branch, main),
                "fixture must be UNMERGED for this test to mean anything",
            )
            self.assertFalse(branching.delete_branch(td, branch, merge_target=main))
            self.assertTrue(
                _bf.branch_exists(td, branch),
                "an unmerged branch must survive: its absence is what the mark-done "
                "gate reads as proof the merge landed",
            )

    def test_refuses_without_a_merge_target_too(self):
        """No target = prove it against HEAD, which is what `-d` is believed to do."""
        with tempfile.TemporaryDirectory() as td:
            branch = "paul/story-007-pushed"
            self._pushed_unmerged_branch(td, branch)

            self.assertFalse(branching.delete_branch(td, branch))
            self.assertTrue(_bf.branch_exists(td, branch))


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

    def test_merged_but_diverged_from_upstream_now_deletes(self):
        """The teammate-close case. Was a silent exit 1; the branch is fully
        merged, so `-D` is provably safe."""
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-002-merged", diverge=True)
            result = _run_delete(td, "paul/story-002-merged")
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
            result = _run_delete(td, "paul/story-003-unmerged")
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
            result = _run_delete(td, "paul/story-004-merged", "--target", main)
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

            result = _run_delete(td, plan_branch, smm_dir=str(smm))

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
            result = _run_delete(td, "paul/story-007-held")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("checked out in a worktree", result.stderr)
            self.assertTrue(_bf.branch_exists(td, "paul/story-007-held"))

    def test_missing_branch_is_not_reported_as_unmerged(self):
        with tempfile.TemporaryDirectory() as td:
            _bf.init_repo(td)
            result = _run_delete(td, "paul/story-404-gone")
            self.assertEqual(result.returncode, 1)
            self.assertIn("paul/story-404-gone", result.stderr)
            self.assertNotIn("not merged", result.stderr)

    def test_unresolvable_target_is_not_reported_as_unmerged(self):
        """`-d` refuses (diverged tracking ref) and the target names nothing, so
        no ancestry was ever proven either way. Claiming "not merged" invents a
        fact; the honest answer is that the target does not resolve."""
        with tempfile.TemporaryDirectory() as td:
            _setup_merged_branch(td, "paul/story-006-merged", diverge=True)
            result = _run_delete(
                td, "paul/story-006-merged", "--target", "no-such-target"
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("no-such-target", result.stderr)
            self.assertNotIn("not merged", result.stderr)


_SPRINT_BRANCH = "paul/sprint-001-open"


def _repo_on_sprint_branch(td: str) -> None:
    """A repo whose sprint branch is cut off main and is AHEAD of it.

    Ahead is the whole point: a story merged into the sprint branch is then
    provably NOT merged into main, so a delete proven against main refuses.
    Leaves HEAD on the sprint branch, so the next ``make_commit`` cuts a story
    branch off it — the real topology.
    """
    _bf.init_repo(td)
    _bf.make_commit(td, _SPRINT_BRANCH, "sprint.txt", "s", "sprint base")


def _seed_open_sprint(smm: Path, *, story_branch: str) -> None:
    """Stage 2 + an OPEN sprint on ``_SPRINT_BRANCH`` owning ``story_branch``.

    The story is ``done`` — that is what makes its branch an ORPHAN in
    kickoff's triage listing (which surfaces branches with no ACTIVE story)
    while the sprint it belongs to is still open. Exactly the reported state.
    """
    _bf.write_system_context(smm, stage=2)
    _bf.seed_sprint_with_stories(
        smm,
        [("story-001", "done")],
        base_branch=_SPRINT_BRANCH,
        story_branches={"story-001": story_branch},
    )


class TestDeleteCLIResolvesCurrentSprintStoryBase(unittest.TestCase):
    """Concern 9df23ed3ec84: a story branch's base is its SPRINT branch, but
    the delete target defaulted to `get_merge_target` — plan branch or primary,
    never the sprint. So every story branch merged into a still-OPEN sprint was
    undeletable via the path kickoff documents: it refused "not merged into
    main". Hit live on three branches, each worked around with `--target`.

    The swap is GATED on current-sprint membership rather than unconditional,
    because kickoff's orphan list also carries PRIOR-sprint story branches,
    whose base already landed and which resolve correctly via `get_merge_target`
    today. An unconditional swap trades the reported bug for that new one.
    """

    def test_story_merged_into_open_sprint_deletes_without_a_target(self):
        """The reported bug, end to end through kickoff's documented command."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            branch = "paul/story-001-work"
            _repo_on_sprint_branch(td)
            _bf.make_commit(td, branch, "w.txt", "x", "story work")
            _checkout_and_merge(td, _SPRINT_BRANCH, branch)
            _seed_open_sprint(Path(smm), story_branch=branch)

            result = _run_delete(td, branch, smm_dir=smm)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, branch))

    def test_story_not_merged_into_its_sprint_base_still_refuses(self):
        """The fix changes WHICH target is proven against, never WHETHER proof
        is required. The refusal must also name the sprint base it actually
        checked — naming 'main' here would be the old lie in a new place."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            branch = "paul/story-001-unmerged"
            _repo_on_sprint_branch(td)
            _bf.make_commit(td, branch, "u.txt", "x", "story work")
            _bf.checkout_main(td)
            _seed_open_sprint(Path(smm), story_branch=branch)

            result = _run_delete(td, branch, smm_dir=smm)

            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("not merged", result.stderr)
            self.assertIn(_SPRINT_BRANCH, result.stderr)
            self.assertTrue(_bf.branch_exists(td, branch), "unmerged work survives")

    def test_prior_sprint_story_branch_still_resolves_via_merge_target(self):
        """The regression the gating exists to prevent — and why membership is
        keyed on the RECORDED branch, not on the story id alone.

        Story ids restart at story-001 every sprint, so a prior sprint's orphan
        branch collides with a current story id as a matter of course. Gating on
        the id alone would resolve THIS sprint's base for it and refuse to
        delete a branch that today deletes cleanly via primary.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            prior, current = "paul/story-001-prior", "paul/story-001-current"
            _repo_on_sprint_branch(td)
            _bf.make_branch(td, current)  # this sprint's story-001, still open
            _bf.checkout_main(td)
            _bf.make_commit(td, prior, "p.txt", "x", "last sprint's work")
            _checkout_and_merge(td, "main", prior)
            _seed_open_sprint(Path(smm), story_branch=current)

            result = _run_delete(td, prior, smm_dir=smm)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, prior))

    def test_explicit_target_beats_the_derived_story_base(self):
        """Same branch, both ways round: the derived base refuses it, the
        explicit target deletes it. Asserting only the second half would pass
        even if --target were being ignored."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            branch = "paul/story-001-on-main"
            _repo_on_sprint_branch(td)
            _bf.checkout_main(td)
            _bf.make_commit(td, branch, "m.txt", "x", "work off main")
            _checkout_and_merge(td, "main", branch)
            _seed_open_sprint(Path(smm), story_branch=branch)

            derived = _run_delete(td, branch, smm_dir=smm)
            self.assertEqual(derived.returncode, 1, derived.stdout)
            self.assertTrue(_bf.branch_exists(td, branch))

            explicit = _run_delete(td, branch, "--target", "main", smm_dir=smm)
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            self.assertFalse(_bf.branch_exists(td, branch))

    def test_non_story_branch_keeps_the_merge_target_fallback(self):
        """A free branch has no story id, so an open sprint changes nothing for
        it — it is still proven against the primary branch."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            branch = "paul/free-tidy-up"
            _repo_on_sprint_branch(td)
            _bf.checkout_main(td)
            _bf.make_commit(td, branch, "f.txt", "x", "free work")
            _checkout_and_merge(td, "main", branch)
            _seed_open_sprint(Path(smm), story_branch="paul/story-001-current")

            result = _run_delete(td, branch, smm_dir=smm)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(_bf.branch_exists(td, branch))


if __name__ == "__main__":
    unittest.main()
