#!/usr/bin/env python3
"""Branch creation refuses a base it cannot trust, and says why.

Split out of test_branching_story_creation.py (which sat at 395 lines) when
this coverage pushed it past the 500-line cap. The two files divide by
question, not by chronology: the sibling asks "does a story branch get created
and resumed correctly?", this one asks "what happens when the base handed to
that creation is a LIE?" — a sprint branch that has vanished, or an empty
string. Both answers must be a refusal, because the fallback base is the
primary branch, and cutting story work off the release branch is silent
corruption that only surfaces at merge time.

A refusal is only half the product: the reason has to be READABLE. The
resolver's message names the sprint, both candidate branches, and the fix, so
the CLI must print it rather than let a traceback bury it.
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
import identity
import sprint_store

_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_make_feature_commit = _bf.append_commit

_CLI = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")


def _run_cli(smm_dir: Path, *argv: str) -> subprocess.CompletedProcess:
    """Invoke branching.py as a real subprocess.

    No USER override in the env: identity.user_namespace reads GIT CONFIG, not
    $USER, so the namespace here is the fixture repo's (test@test.com -> "test").
    Seeding a "paul/..." branch and expecting the CLI to find it is what made an
    earlier version of the blank-base resume test pass for the wrong reason —
    the name never matched, so it silently exercised the CREATE arm.
    """
    return subprocess.run(
        [sys.executable, _CLI, "--smm-dir", str(smm_dir), *argv],
        capture_output=True,
        text=True,
        env=_bf.GIT_ENV,
    )


class TestCreateStoryBranchRefusesDegradedBase(unittest.TestCase):
    """A sprint EXISTS at stage 2+ but its branch is GONE. The old code
    silently handed `git checkout -b <story> <primary>` the release branch.
    Both arms of _create_or_resume_branch have to refuse.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._smm = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(self._smm.cleanup)
        self.td = self._td.name
        self.smm_dir = Path(self._smm.name)
        _init_repo(self.td)
        _write_system_context(self.smm_dir, stage=2)
        # sprint-042 recorded against a branch that does not exist, and the
        # slug-rebuilt name (paul/sprint-042-ship-it) does not exist either.
        _bf.write_sprint_json(self.smm_dir, "sprint-042", "ship it")
        sprint_store.set_branch(self.smm_dir, "paul/sprint-042-deleted")
        ns = patch("branching.identity.user_namespace", return_value="paul")
        ns.start()
        self.addCleanup(ns.stop)

    def test_create_arm_raises_and_creates_nothing(self):
        with self.assertRaises(ValueError):
            branching.create_story_branch(self.td, "story-001", "new", self.smm_dir)
        self.assertFalse(_bf.branch_exists(self.td, "paul/story-001-new"))
        self.assertEqual(_get_current_branch(self.td), "main")

    def test_resume_arm_does_not_fast_forward_story_onto_primary(self):
        """The nastier half. A story branch with no unique commits IS an
        ancestor of main, so _fast_forward_if_safe would happily fast-forward
        it onto the release branch — silently re-parenting a branch the user
        believes is sprint-based, picking up everything landed on main since
        the fork, which story-close then merges straight back INTO main. It
        only ever printed a `note:` to stderr.
        """
        _bf.make_branch(self.td, "paul/story-001-resume")
        forked_at = _bf.get_head_sha(self.td)
        _make_feature_commit(self.td, "landed-on-main.txt")  # primary advances
        self.assertNotEqual(_bf.get_head_sha(self.td), forked_at)

        with self.assertRaises(ValueError):
            branching.create_story_branch(self.td, "story-001", "resume", self.smm_dir)

        self.assertEqual(
            _bf.get_branch_sha(self.td, "paul/story-001-resume"),
            forked_at,
            "Resumed story branch was fast-forwarded onto primary — it now "
            "carries every commit landed on the release branch since the fork.",
        )


class TestCreateStoryBranchRefusesUnresolvableHandedBase(unittest.TestCase):
    """The base the caller HANDS us has to exist too.

    This is the arm that guards the shipped path: xp-assign and xp-schedule
    capture a base from `get-base` and always pass --base explicitly, so a
    guard that only covers base=None never runs in production (decision
    harden-the-capture-not-the-default). An unresolvable handed base is the
    same failure in a different hat — the CREATE arm errors out of git, but the
    RESUME arm silently swallows it and reports the branch as resumed.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._smm = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(self._smm.cleanup)
        self.td = self._td.name
        self.smm_dir = Path(self._smm.name)
        _init_repo(self.td)
        _write_system_context(self.smm_dir, stage=2)
        ns = patch("branching.identity.user_namespace", return_value="paul")
        ns.start()
        self.addCleanup(ns.stop)

    def test_nonexistent_handed_base_refused_on_create_arm(self):
        with self.assertRaises(ValueError):
            branching.create_story_branch(
                self.td, "story-001", "typo", self.smm_dir, base="paul/sprint-042-typo"
            )
        self.assertFalse(_bf.branch_exists(self.td, "paul/story-001-typo"))

    def test_nonexistent_handed_base_refused_on_resume_arm(self):
        """The silent one. _fast_forward_if_safe no-ops against a ref git cannot
        resolve, so this checked the branch out and reported success — the story
        branch never moved to the base the caller thought it named.
        """
        _bf.make_branch(self.td, "paul/story-001-typo")
        with self.assertRaises(ValueError):
            branching.create_story_branch(
                self.td, "story-001", "typo", self.smm_dir, base="paul/sprint-042-typo"
            )

    def test_a_real_sha_is_still_a_valid_handed_base(self):
        """Chained stories fork off a commit, so the check must accept any ref
        git resolves — a bare SHA, not just a local branch name.
        """
        _make_feature_commit(self.td, "first.txt")
        base_sha = _bf.get_head_sha(self.td)
        _make_feature_commit(self.td, "second.txt")

        result = branching.create_story_branch(
            self.td, "story-002", "chained", self.smm_dir, base=base_sha
        )

        self.assertEqual(result, "paul/story-002-chained")
        self.assertEqual(_bf.get_head_sha(self.td), base_sha)

    def test_below_the_floor_a_bad_base_is_moot_not_fatal(self):
        """Stage 0 is plugin-inert: no branch is cut, so an unusable base must
        skip cleanly rather than raise. Refusing here would make the branching
        doctrine fire in a repo that opted out of it.
        """
        _write_system_context(self.smm_dir, stage=0)
        result = branching.create_story_branch(
            self.td, "story-001", "off", self.smm_dir, base="does-not-exist"
        )
        self.assertIsNone(result)


class TestCLIReportsUnresolvableBase(unittest.TestCase):
    """The refusal has to arrive as a MESSAGE, not a stack trace.

    `branching.py create` without --base reaches the raising resolver (the
    SKILLs pass --base; the bare CLI does not). Its ValueError carries the
    entire product of the refusal — the sprint, both candidate branch names,
    the primary it declined to silently fall back to, and the fix. Every other
    ValueError in this CLI (accept-env, find-closing-teammate-worktree) is
    caught and printed; this one must be too, or the one thing the user has to
    read is buried under a traceback.
    """

    def test_unresolvable_base_prints_the_reason_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _bf.write_sprint_json(smm_dir, "sprint-042", "ship it")
            sprint_store.set_branch(smm_dir, "test/sprint-042-deleted")

            r = _run_cli(
                smm_dir,
                *["create", "--cwd", td, "--story", "story-001", "--slug", "boom"],
            )

            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertNotIn(
                "Traceback",
                r.stderr,
                "the refusal reached the user as a stack trace — the message "
                "naming the sprint and the fix is what makes it actionable",
            )
            self.assertIn("sprint-042", r.stderr)
            self.assertIn("test/sprint-042-deleted", r.stderr)
            self.assertFalse(
                _bf.branch_exists(td, f"{identity.user_namespace(td)}/story-001-boom")
            )


class TestCLIRejectsBlankBase(unittest.TestCase):
    """argparse yields "" for `--base ""`, not None, so a blank base sails past
    the `base is None` check. On the CREATE arm git rejects the empty ref and we
    exit 1 by accident; on the RESUME arm nothing rejects it — the branch is
    checked out, `_fast_forward_if_safe(cwd, name, "")` quietly no-ops, and the
    CLI reports `resumed:` and exits 0. A caller that fumbled its base ("$BASE"
    empty because its resolver refused, in a SKILL with no `set -e`) is told
    everything is fine.

    Both --base-taking commands are covered: `create` is where an empty base is
    likeliest, but `create-free` takes the same flag through the same resume arm.
    """

    def _setup(self, td: str, smm: str) -> tuple[Path, str]:
        """Returns (smm_dir, the user namespace the CLI will actually use)."""
        _init_repo(td)
        smm_dir = Path(smm)
        _write_system_context(smm_dir, stage=2)
        return smm_dir, identity.user_namespace(td)

    def _assert_refused(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(result.stderr.strip(), "must say WHY it refused")
        self.assertNotIn("resumed", result.stdout)
        self.assertNotIn("created", result.stdout)

    def _create(self, td: str, smm_dir: Path) -> subprocess.CompletedProcess:
        return _run_cli(
            smm_dir,
            *["create", "--cwd", td, "--story", "story-001", "--slug", "blank"],
            *["--base", ""],
        )

    def _create_free(self, td: str, smm_dir: Path) -> subprocess.CompletedProcess:
        return _run_cli(
            smm_dir,
            *["create-free", "--cwd", td, "--slug", "blank"],
            *["--base", ""],
        )

    def test_blank_base_refused_on_create_arm(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir, ns = self._setup(td, smm)
            self._assert_refused(self._create(td, smm_dir))
            self.assertFalse(_bf.branch_exists(td, f"{ns}/story-001-blank"))

    def test_blank_base_refused_on_resume_arm(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir, ns = self._setup(td, smm)
            _bf.make_branch(td, f"{ns}/story-001-blank")
            self.assertTrue(
                _bf.branch_exists(td, f"{ns}/story-001-blank"), "resume arm not armed"
            )
            self._assert_refused(self._create(td, smm_dir))

    def test_blank_base_refused_by_create_free_on_resume_arm(self):
        """The sibling leg. create-free takes the same --base through the same
        silent resume arm, so guarding only `create` moved the hole rather than
        closing it: this reported `resumed: <branch>` and exited 0.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir, ns = self._setup(td, smm)
            free_branch = branching.free_branch_name(ns, "blank")
            _bf.make_branch(td, free_branch)
            self.assertTrue(_bf.branch_exists(td, free_branch), "resume arm not armed")
            self._assert_refused(self._create_free(td, smm_dir))


class TestCreateFreeRefusesUnresolvableHandedBase(unittest.TestCase):
    """A blank base is only HALF of create-free's hole. `--base` is a documented
    human-typed escape hatch ("fork this free branch off <ref>"), so the likeliest
    bad value is not "" but a TYPO — and a typo takes the identical silent path:
    `_fast_forward_if_safe` no-ops against a ref git cannot resolve, and the CLI
    prints `resumed: <branch>` and exits 0 with the branch still pointing wherever
    it was. `create` refuses this; refusing one caller of the same resume arm and
    not the other leaves the hole open under a different key.
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._smm = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(self._smm.cleanup)
        self.td = self._td.name
        self.smm_dir = Path(self._smm.name)
        _init_repo(self.td)
        _write_system_context(self.smm_dir, stage=2)
        self.ns = identity.user_namespace(self.td)
        self.free = branching.free_branch_name(self.ns, "docs")

    def _create_free(self, base: str) -> subprocess.CompletedProcess:
        return _run_cli(
            self.smm_dir,
            *["create-free", "--cwd", self.td, "--slug", "docs"],
            *["--base", base],
        )

    def test_typo_base_refused_on_resume_arm_rather_than_reported_resumed(self):
        _bf.make_branch(self.td, self.free)
        pinned = _bf.get_head_sha(self.td)
        _make_feature_commit(self.td, "landed.txt")  # the free branch is now behind

        r = self._create_free("paul/plan-typoo")

        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertNotIn("resumed", r.stdout)
        self.assertTrue(r.stderr.strip(), "must say WHY it refused")
        self.assertIn("paul/plan-typoo", r.stderr)
        self.assertEqual(
            _bf.get_branch_sha(self.td, self.free),
            pinned,
            "the branch must not have moved",
        )

    def test_typo_base_refused_on_create_arm(self):
        r = self._create_free("paul/plan-typoo")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertFalse(_bf.branch_exists(self.td, self.free))

    def test_a_real_ref_is_still_accepted(self):
        _make_feature_commit(self.td, "first.txt")
        base_sha = _bf.get_head_sha(self.td)
        r = self._create_free(base_sha)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_bf.get_branch_sha(self.td, self.free), base_sha)


if __name__ == "__main__":
    unittest.main()
