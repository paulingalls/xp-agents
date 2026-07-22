#!/usr/bin/env python3
"""Tests for spawn's held-branch recovery — `_release_branch_from_main`.

`branching.py create` leaves the MAIN checkout on the branch it just cut, and
the very next `git worktree add <path> <that branch>` exits 128: git refuses to
check out a branch that is already checked out somewhere else. Until now the
only thing standing between the two was a second, hand-written
`git checkout "$BASE"` in /xp-assign's SKILL.md — dropping it by hand is exactly
how this was found. The recovery moves that precondition into spawn itself.

A NEW file rather than more cases in `test_spawn_teammate.py`: that file is at
488 lines against the project's 500-line cap and these pins cross it.
Worktree creation/cleanup pins live in `test_spawn_worktree.py`; this file owns
only the release-the-held-branch behaviour.
"""

import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branch_lifecycle
import spawn_teammate
import worktree
from _branching_fixtures import (
    GIT_ENV,
    get_current_branch,
    make_commit,
    seed_sprint_with_stories,
    write_system_context,
)
from conftest import _PLUGIN_ROOT, _IntegrationTestCase, cleanup_test_worktrees


@contextmanager
def _git_argv_spy():
    """Record every git argv the process shells out, running them for real.

    Patches ``subprocess.run`` itself (every module here reaches git through
    ``subprocess.run``, not a ``from subprocess import run`` alias), so the spy
    sees the recovery's checkout wherever it is issued from. Yields the list of
    argvs; assert on it rather than on end state — an UNCONDITIONAL checkout
    leaves the same end state as no checkout at all when main is already on the
    base, and would sail past a weaker assertion.
    """
    real_run = subprocess.run
    calls: list[list[str]] = []

    def spy(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)):
            calls.append([str(part) for part in cmd])
        return real_run(cmd, *args, **kwargs)

    with patch("subprocess.run", spy):
        yield calls


def _checkouts(calls: list[list[str]]) -> list[list[str]]:
    """The `git checkout ...` argvs among the spied calls."""
    return [c for c in calls if c[:2] == ["git", "checkout"]]


class _HeldBranchTestCase(_IntegrationTestCase):
    """Shared repo shaping: a sprint base branch, a story branch cut from it,
    and a sprint.json that records the base so the required resolver can find it.
    """

    def setUp(self):
        super().setUp()
        # setUp scrubs the worktree but leaves HEAD wherever a sibling test put
        # it; these tests are entirely about which branch the checkout is on.
        self._reset_repo_to_main()

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
            env=GIT_ENV,
        )

    def _record_sprint_base(self, base: str) -> None:
        """Record `base` as the sprint's branch_name at branching stage 2.

        The full `write_system_context` doc, not a stage-only stub: this SMM is
        also read by `create_worktree`'s bootstrap step, which validates the
        system context loudly and would reject a partial one.
        """
        seed_sprint_with_stories(self.smm_dir, [], base_branch=base)
        write_system_context(self.smm_dir, 2)

    def _seed_base_and_story(self, base: str, story: str) -> None:
        """Cut `base` off main and `story` off `base`, leaving the MAIN checkout
        ON `story` — the state `branching.py create` hands the next spawn.

        Records `base` as the sprint's branch_name at stage 2, so
        ``get_story_base_branch_required`` resolves the SPRINT base rather than
        degrading to the primary/release branch.
        """
        make_commit(
            str(self.tmpdir),
            base,
            f"{base.replace('/', '-')}.txt",
            "base",
            f"seed {base}",
        )
        self._git("checkout", "-b", story)
        self._record_sprint_base(base)


class TestReleasesHeldBranch(_HeldBranchTestCase):
    """AC1 + AC2: recover when main holds the target branch, and ONLY then."""

    def test_recovers_when_main_holds_the_target_branch(self):
        """The live failure. Main is on the story branch (where `create` left
        it), spawn is handed that same branch — today `git worktree add` exits
        128 before the agent ever starts."""
        base, story = "sprint-base-070", "paulingalls/story-070-held"
        self._seed_base_and_story(base, story)
        self.assertEqual(get_current_branch(str(self.tmpdir)), story)

        wt_path = spawn_teammate.create_worktree(
            "worktree-story-070",
            str(self.tmpdir),
            branch=story,
            smm_dir=self.smm_dir,
        )

        self.assertTrue(Path(wt_path).is_dir(), "worktree add did not run")
        self.assertEqual(get_current_branch(wt_path), story)
        self.assertEqual(
            get_current_branch(str(self.tmpdir)),
            base,
            "main must be returned to the STORY BASE, not left on the branch "
            "the worktree now holds",
        )

    def test_checks_away_to_the_sprint_base_not_the_primary_branch(self):
        """The base is resolved through the same `--required` resolver
        /xp-assign uses, so spawn and assign cannot disagree about what "base"
        means — and neither can silently degrade to the release branch."""
        base, story = "sprint-base-071", "paulingalls/story-071-resolver"
        self._seed_base_and_story(base, story)

        spawn_teammate.create_worktree(
            "worktree-story-071",
            str(self.tmpdir),
            branch=story,
            smm_dir=self.smm_dir,
        )

        landed = get_current_branch(str(self.tmpdir))
        self.assertEqual(landed, base)
        self.assertNotEqual(landed, "main", "degraded to the release branch")

    def test_no_checkout_when_main_is_already_on_the_base(self):
        """The recovery is CONDITIONAL. With main already on the base there is
        nothing to release, so not a single checkout is issued.

        Asserted on the git argv, not the end state: an unconditional
        `git checkout <base>` also ends with main on the base, and would pass
        an end-state-only assertion while re-checking-out the tree on every
        spawn.
        """
        base, story = "sprint-base-072", "paulingalls/story-072-conditional"
        self._seed_base_and_story(base, story)
        self._git("checkout", base)

        with _git_argv_spy() as calls:
            spawn_teammate.create_worktree(
                "worktree-story-072",
                str(self.tmpdir),
                branch=story,
                smm_dir=self.smm_dir,
            )

        self.assertEqual(
            _checkouts(calls),
            [],
            "no checkout may be issued when main is already on the base",
        )
        self.assertEqual(get_current_branch(str(self.tmpdir)), base)


class TestRefusesRatherThanLosingWork(_HeldBranchTestCase):
    """AC3: uncommitted work in the main checkout STOPS the spawn.

    Never `--force`. This mirrors the philosophy `cleanup_existing` already
    documents — `force=False` hands the decision to git, which refuses to
    clobber modified or untracked files — and the failure has to be actionable,
    so it carries the branch, the base, and git's own stderr.
    """

    def _seed_divergent_dirty(self, base: str, story: str, filename: str) -> None:
        """Main on `story`, holding an uncommitted edit that `git checkout
        <base>` cannot carry across.

        The divergent COMMIT is what makes this fixture work. A story branch is
        cut from its base, so the two trees are identical and git cheerfully
        carries a modified file across — no refusal, nothing to pin. Committing
        a different body on the story branch first means checking away would
        have to overwrite the local edit, and git actually refuses.
        """
        make_commit(str(self.tmpdir), base, filename, "base body\n", f"seed {base}")
        make_commit(
            str(self.tmpdir), story, filename, "story body\n", f"diverge {story}"
        )
        (self.tmpdir / filename).write_text("hours of uncommitted work\n")
        self._record_sprint_base(base)

    def test_refuses_with_an_actionable_reason_and_keeps_the_work(self):
        base, story = "sprint-base-073", "paulingalls/story-073-dirty"
        filename = "held.txt"
        self._seed_divergent_dirty(base, story, filename)

        with self.assertRaises(RuntimeError) as ctx:
            spawn_teammate.create_worktree(
                "worktree-story-073",
                str(self.tmpdir),
                branch=story,
                smm_dir=self.smm_dir,
            )

        message = str(ctx.exception)
        self.assertIn(story, message, "the refusal must name the held branch")
        self.assertIn(base, message, "the refusal must name the base")
        self.assertIn(
            filename,
            message,
            "git's stderr must be relayed — the blocking file is the only "
            "actionable part of it, and CalledProcessError carries none of it",
        )
        self.assertEqual(
            (self.tmpdir / filename).read_text(),
            "hours of uncommitted work\n",
            "the uncommitted work was discarded by the recovery",
        )
        self.assertEqual(get_current_branch(str(self.tmpdir)), story)

    def test_refusal_leaves_no_worktree_behind(self):
        """The recovery runs BEFORE `git worktree add`, so a refusal leaves no
        half-provisioned tree for the lead to clean up."""
        base, story = "sprint-base-074", "paulingalls/story-074-dirty"
        self._seed_divergent_dirty(base, story, "held.txt")
        name = "worktree-story-074"

        with self.assertRaises(RuntimeError):
            spawn_teammate.create_worktree(
                name, str(self.tmpdir), branch=story, smm_dir=self.smm_dir
            )

        self.assertFalse(worktree.worktree_path(name, str(self.tmpdir)).is_dir())


class TestTransientContentionIsRetried(_HeldBranchTestCase):
    """The recovery's checkout runs in the most contended spot in the flow —
    immediately before a `git worktree add`, inside a fan-out where sibling
    spawns are taking the index and rewriting the worktree registry. Both
    signatures `branch_lifecycle` already retries are live here, and either one
    would otherwise surface as the "commit or stash your work" refusal, sending
    the lead after uncommitted work that does not exist.
    """

    def _spawn_with_first_checkout_failing(self, stderr: str, story: str, name: str):
        """Fail the FIRST `git checkout` with `stderr`, then run git for real.

        Patched at `branch_lifecycle._git` — the layer the retry wraps — so the
        retry loop itself is exercised rather than stubbed.
        """
        real_git = branch_lifecycle._git
        attempts: list[list[str]] = []

        def flaky(args, cwd):
            if args[:2] == ["git", "checkout"]:
                attempts.append(args)
                if len(attempts) == 1:
                    return subprocess.CompletedProcess(args, 128, "", stderr)
            return real_git(args, cwd)

        with patch.object(branch_lifecycle, "_git", flaky):
            wt_path = spawn_teammate.create_worktree(
                name, str(self.tmpdir), branch=story, smm_dir=self.smm_dir
            )
        return attempts, wt_path

    def test_index_lock_collision_is_retried_not_reported_as_dirty(self):
        base, story = "sprint-base-079", "paulingalls/story-079-lock"
        self._seed_base_and_story(base, story)

        attempts, wt_path = self._spawn_with_first_checkout_failing(
            "fatal: Unable to create '/repo/.git/index.lock': File exists.\n",
            story,
            "worktree-story-079",
        )

        self.assertEqual(len(attempts), 2, "the index.lock collision must retry")
        self.assertEqual(get_current_branch(str(self.tmpdir)), base)
        self.assertEqual(get_current_branch(wt_path), story)

    def test_worktree_registry_misread_is_retried(self):
        """The signature story-020 measured live: a concurrent worktree
        add/remove makes `git checkout` transiently misreport our own target as
        held elsewhere."""
        base, story = "sprint-base-080", "paulingalls/story-080-registry"
        self._seed_base_and_story(base, story)

        attempts, wt_path = self._spawn_with_first_checkout_failing(
            f"fatal: '{base}' is already used by worktree at '/somewhere'\n",
            story,
            "worktree-story-080",
        )

        self.assertEqual(len(attempts), 2, "the registry misread must retry")
        self.assertEqual(get_current_branch(str(self.tmpdir)), base)
        self.assertEqual(get_current_branch(wt_path), story)


class TestRecoveryScope(_HeldBranchTestCase):
    """AC4 + characterization: the arms the recovery must NOT reach."""

    def test_in_place_spawn_performs_no_recovery(self):
        """An in-place (solo) spawn intentionally RUNS on the checked-out story
        branch — checking it away would pull the teammate's own tree out from
        under it. It holds by construction (the in-place arm never calls
        `create_worktree`); pinned so a later refactor cannot lift the recovery
        up into `main`.
        """
        prompt_file = self.tmpdir / "p.prompt.txt"
        prompt_file.write_text("BODY for story-075")
        released: list[tuple] = []

        with (
            patch.object(
                spawn_teammate,
                "_release_branch_from_main",
                side_effect=lambda *a, **kw: released.append((a, kw)),
            ),
            patch.object(spawn_teammate, "run_with_tee", return_value=False),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "worktree-story-075",
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    str(prompt_file),
                    "--story-id",
                    "story-075",
                    "--in-place",
                ]
            )

        self.assertEqual(released, [], "in-place must not release any branch")

    def test_branch_none_create_is_unchanged(self):
        """The fixture path (`worktree add -b <name>`) cuts its own branch off
        whatever main is on — there is no handed branch to be held, so the
        recovery must not fire and main must not move."""
        self._git("checkout", "-b", "sprint-base-076")

        with _git_argv_spy() as calls:
            wt_path = spawn_teammate.create_worktree(
                "worktree-story-076", str(self.tmpdir), smm_dir=self.smm_dir
            )

        self.assertEqual(_checkouts(calls), [])
        self.assertTrue(Path(wt_path).is_dir())
        self.assertEqual(get_current_branch(str(self.tmpdir)), "sprint-base-076")

    def test_smm_dir_none_skips_the_recovery(self):
        """With no SMM dir there is no honest base to resolve, so the recovery
        SKIPS rather than guessing one — behaviour identical to before it
        existed, git's own 128 included.

        Only reachable from positional test callers: `--smm-dir` is required and
        `main` always passes it, so the shipped path always has a base to
        resolve. Those callers pass no `branch` either, which is why this leg
        costs nothing in practice.
        """
        base, story = "sprint-base-077", "paulingalls/story-077-nosmm"
        self._seed_base_and_story(base, story)

        with self.assertRaises(subprocess.CalledProcessError):
            spawn_teammate.create_worktree(
                "worktree-story-077", str(self.tmpdir), branch=story
            )

        self.assertEqual(get_current_branch(str(self.tmpdir)), story)


class TestCreateThenSpawnEndToEnd(_HeldBranchTestCase):
    """E2E: `branching.py create` followed DIRECTLY by a spawn, with no manual
    checkout in between. That exact sequence exits 128 today, and it is the
    sequence /xp-assign runs — its second `git checkout "$BASE"` is the only
    thing that ever made it work, and nothing enforced that line.
    """

    def _branching_create(self, story_id: str, slug: str, base: str) -> str:
        """Run the real `branching.py create` and return the branch it made.

        It leaves the main checkout ON that branch — the precondition under
        test — so nothing here checks away afterwards.
        """
        result = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "create",
                "--cwd",
                str(self.tmpdir),
                "--story",
                story_id,
                "--slug",
                slug,
                "--base",
                base,
            ],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, f"branching.py create: {result.stderr}")
        self.assertTrue(
            result.stdout.startswith("created: "),
            f"expected a created branch, got: {result.stdout!r}",
        )
        return result.stdout.split("created: ", 1)[1].strip()

    def test_create_then_spawn_needs_no_manual_checkout(self):
        base = "sprint-base-078"
        make_commit(str(self.tmpdir), base, "e2e.txt", "base", f"seed {base}")
        self._record_sprint_base(base)

        branch = self._branching_create("story-078", "e2e-held", base)
        self.assertEqual(
            get_current_branch(str(self.tmpdir)),
            branch,
            "precondition: create must leave the main checkout on the new branch",
        )

        wt_path = spawn_teammate.create_worktree(
            "worktree-story-078", str(self.tmpdir), branch=branch, smm_dir=self.smm_dir
        )

        self.assertEqual(get_current_branch(wt_path), branch)
        self.assertEqual(get_current_branch(str(self.tmpdir)), base)


if __name__ == "__main__":
    unittest.main()
