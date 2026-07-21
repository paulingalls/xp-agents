#!/usr/bin/env python3
"""Tests for branch_resolution.py — SMM-state -> branch/stage answers.

Home for all resolver coverage: the stage machinery, the recorded-name
lookups, and the story-base resolution that /xp-assign, /xp-schedule and
/xp-story-close branch from or merge into.

test_branching.py and test_branching_plan.py are both already over the
500-line cap; new resolver coverage lands here, not there.
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
import branch_resolution
import branching
import sprint_store


class TestBranchResolutionShimImports(unittest.TestCase):
    """Catch cascade failure in <1s when the branch_resolution extraction
    breaks the backwards-compat re-exports — mirrors
    TestBranchLifecycleShimImports (test_branching.py) per wisdom
    ab40b12643ab.

    The PRIVATES are load-bearing, not incidental: test_branching_cli_detection
    calls branching._recorded_plan_branch directly, and several suites patch
    branching._git / branching.branch_exists.
    """

    def test_resolution_symbols_resolve_via_branching(self):
        from branching import (
            _DEFAULT_PRIMARY,
            _PROTECTED_BRANCHES,
            _git,
            _load_branching_strategy,
            _maybe_auto_promote,
            _recorded_plan_branch,
            _recorded_sprint_branch,
            branch_exists,
            get_branching_stage,
            get_merge_target,
            get_primary_branch,
            get_protected_branches,
            get_story_base_branch,
            is_protected_branch,
            match_local_branches,
            resolve_sprint_branch_name,
        )

        for fn in (
            _git,
            _load_branching_strategy,
            _maybe_auto_promote,
            _recorded_plan_branch,
            _recorded_sprint_branch,
            branch_exists,
            get_branching_stage,
            get_merge_target,
            get_primary_branch,
            get_protected_branches,
            get_story_base_branch,
            is_protected_branch,
            match_local_branches,
            resolve_sprint_branch_name,
        ):
            self.assertTrue(callable(fn))
        self.assertEqual(_DEFAULT_PRIMARY, "main")
        self.assertEqual(_PROTECTED_BRANCHES, {"main", "master"})

    def test_branching_re_exports_the_same_objects(self):
        """One definition, one importer — the re-export must be identity, not
        a copy. A duplicated definition (the branch_lifecycle._git precedent)
        would make `patch("branching._git")` and the resolver's own `_git`
        diverge silently."""
        self.assertIs(branching.branch_exists, branch_resolution.branch_exists)
        self.assertIs(
            branching.get_story_base_branch, branch_resolution.get_story_base_branch
        )
        self.assertIs(branching._git, branch_resolution._git)


class _ResolverTestCase(unittest.TestCase):
    """Real git repo + real SMM — a resolver's answer only means something
    against branches that actually exist."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self._smm = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.addCleanup(self._smm.cleanup)
        self.cwd = self._td.name
        self.smm_dir = Path(self._smm.name)
        _bf.init_repo(self.cwd)
        ns = patch("branch_resolution.identity.user_namespace", return_value="paul")
        ns.start()
        self.addCleanup(ns.stop)

    def _make_branch(self, name: str) -> None:
        subprocess.run(
            ["git", "branch", name], cwd=self.cwd, capture_output=True, check=True
        )

    def _seed_sprint(self, *, branch_name: str | None = None) -> None:
        """sprint-042, goal 'ship it' -> slug-rebuilt name paul/sprint-042-ship-it."""
        _bf.write_sprint_json(self.smm_dir, "sprint-042", "ship it")
        if branch_name is not None:
            sprint_store.set_branch(self.smm_dir, branch_name)

    def _resolve(self):
        return branch_resolution.resolve_story_base(self.smm_dir, self.cwd)

    def _degrading(self) -> str:
        return branch_resolution.get_story_base_branch(self.smm_dir, self.cwd)

    def _required(self) -> str:
        return branch_resolution.get_story_base_branch_required(self.smm_dir, self.cwd)


class TestIntegrationBranchHealedAtUse(_ResolverTestCase):
    """THE BUG. `integration_branch` was type-checked only, and
    `get_primary_branch` returns it straight to callers that hand it to `git
    checkout` / `git merge` as argv. A stored `-f` therefore becomes `git
    checkout -f`, which DISCARDS LOCAL CHANGES.

    Healing happens HERE, at the use site, not in the loader: the loader feeds
    `_maybe_auto_promote`'s load → mutate → save, so a healing loader would
    persist the substitute over the branch a user configured.
    """

    def _seed(self, integration_branch: object) -> None:
        _bf.write_system_context(
            self.smm_dir, stage=3, integration_branch=integration_branch
        )

    def test_leading_dash_value_resolves_to_primary_not_to_git(self) -> None:
        self._seed("-f")
        self.assertEqual(branch_resolution.get_primary_branch(self.smm_dir), "main")

    def test_pattern_violating_value_resolves_to_primary(self) -> None:
        self._seed("feature branch")
        self.assertEqual(branch_resolution.get_primary_branch(self.smm_dir), "main")

    def test_substitution_is_logged_not_silent(self) -> None:
        """A configured value WAS present and we are targeting something else
        — that changes a merge/checkout target, so it must not be silent."""
        self._seed("-f")
        with patch("branch_resolution._common.log_hook_error") as log:
            branch_resolution.get_primary_branch(self.smm_dir)
        self.assertEqual(log.call_count, 1)
        logged = repr(log.call_args)
        self.assertIn("-f", logged)
        self.assertIn("main", logged)

    def test_usable_value_is_returned_unhealed_and_unlogged(self) -> None:
        self._seed("develop")
        with patch("branch_resolution._common.log_hook_error") as log:
            self.assertEqual(
                branch_resolution.get_primary_branch(self.smm_dir), "develop"
            )
        log.assert_not_called()

    def test_null_value_falls_back_quietly(self) -> None:
        """Null is not a substitution — nothing was configured, so primary IS
        the answer. Logging here would fire on every stage-3 repo that never
        set the field."""
        self._seed(None)
        with patch("branch_resolution._common.log_hook_error") as log:
            self.assertEqual(branch_resolution.get_primary_branch(self.smm_dir), "main")
        log.assert_not_called()

    def test_below_stage_3_is_unaffected(self) -> None:
        _bf.write_system_context(self.smm_dir, stage=2, integration_branch="-f")
        self.assertEqual(branch_resolution.get_primary_branch(self.smm_dir), "main")

    def test_protected_branches_drops_an_unusable_value(self) -> None:
        """Same helper, one answer — the raw-JSON reader and the validated
        loader cannot disagree about what this value resolves to."""
        self._seed("-f")
        self.assertEqual(
            branch_resolution.get_protected_branches(self.smm_dir, 3),
            {"main", "master"},
        )

    def test_protected_branches_does_not_log(self) -> None:
        """No log on this path: a dropped protected entry is the lesser event,
        and this runs on every Bash PreToolUse."""
        self._seed("-f")
        with patch("branch_resolution._common.log_hook_error") as log:
            branch_resolution.get_protected_branches(self.smm_dir, 3)
        log.assert_not_called()

    def test_protected_branches_keeps_a_usable_value(self) -> None:
        self._seed("develop")
        self.assertEqual(
            branch_resolution.get_protected_branches(self.smm_dir, 3),
            {"main", "master", "develop"},
        )


class TestResolveStoryBaseLegitimateDegradation(_ResolverTestCase):
    """The two states where primary is the TRUE answer, not a fallback.

    These are the over-fire canaries. Scoping the raise to the one dishonest
    state is what keeps the fail-loud from taking down callers that are merely
    below the branching floor or doing ad-hoc work.
    """

    def test_below_stage_2_returns_primary_without_raising(self):
        _bf.write_system_context(self.smm_dir, stage=0)
        self._seed_sprint(branch_name="paul/sprint-042-gone")
        self.assertEqual(self._resolve(), "main")
        self.assertEqual(self._required(), "main")

    def test_no_sprint_returns_primary_without_raising(self):
        """THE over-fire canary. Stage 2 with NO sprint is free/ad-hoc work —
        primary is correct, not a guess. test_story_close's
        test_emits_target_branch_via_get_base runs in exactly this state; if
        _required raises here, the fail-loud was aimed in the wrong direction.
        """
        _bf.write_system_context(self.smm_dir, stage=2)
        self.assertFalse((self.smm_dir / "sprint.json").exists())
        self.assertEqual(self._resolve(), "main")
        self.assertEqual(self._required(), "main")


class TestResolveStoryBaseResolvesRealBranches(_ResolverTestCase):
    def test_recorded_branch_wins_when_it_exists(self):
        _bf.write_system_context(self.smm_dir, stage=2)
        self._make_branch("paul/sprint-042-recorded")
        self._seed_sprint(branch_name="paul/sprint-042-recorded")
        self.assertEqual(self._resolve(), "paul/sprint-042-recorded")
        self.assertEqual(self._required(), "paul/sprint-042-recorded")

    def test_stale_recorded_falls_back_to_slug_rebuild(self):
        """A recorded name whose branch is GONE is stale, not authoritative —
        the slug rebuild covers sprints written before the branch name was
        recorded atomically at create time."""
        _bf.write_system_context(self.smm_dir, stage=2)
        self._make_branch("paul/sprint-042-ship-it")  # the slug-rebuilt name
        self._seed_sprint(branch_name="paul/sprint-042-deleted")
        self.assertEqual(self._resolve(), "paul/sprint-042-ship-it")
        self.assertEqual(self._required(), "paul/sprint-042-ship-it")


class TestResolveStoryBaseFailsLoud(_ResolverTestCase):
    """THE BUG. A sprint EXISTS at stage >= 2 but neither candidate name
    resolves locally. The old code silently returned primary — which is main,
    and pushing main RELEASES. Story branches got cut off the release branch.
    """

    def setUp(self) -> None:
        super().setUp()
        _bf.write_system_context(self.smm_dir, stage=2)
        self._seed_sprint(branch_name="paul/sprint-042-deleted")
        # Neither the recorded name nor paul/sprint-042-ship-it exists.

    def test_resolve_returns_none(self):
        self.assertIsNone(self._resolve())

    def test_degrading_caller_still_gets_primary(self):
        """PINS the degrading contract. sprint_stop_gate must keep measuring
        commits_ahead, acceptance_env.recover must keep healing, and
        xp-quality-review must keep computing a diff range. A raise here would
        take down gates that are only trying to OBSERVE."""
        self.assertEqual(self._degrading(), "main")

    def test_required_caller_raises_naming_everything_it_refused(self):
        with self.assertRaises(ValueError) as ctx:
            self._required()
        msg = str(ctx.exception)
        self.assertIn("sprint-042", msg)
        self.assertIn("paul/sprint-042-deleted", msg)  # the recorded branch
        self.assertIn("paul/sprint-042-ship-it", msg)  # the slug-rebuilt name
        self.assertIn("'main'", msg)  # the primary it REFUSED to return
        self.assertIn("re-cut", msg)  # and the way out

    def test_no_recorded_branch_at_all_still_raises(self):
        """branch_name absent (not just stale) — the slug rebuild is the only
        candidate, and it does not exist either."""
        _bf.write_sprint_json(self.smm_dir, "sprint-042", "ship it")
        self.assertIsNone(self._resolve())
        with self.assertRaises(ValueError):
            self._required()


class TestResolveStoryBaseCorruptSprint(_ResolverTestCase):
    """A corrupt sprint.json must CRASH, not degrade. resolve_story_base runs
    ABOVE the stage gate and feeds the branch we merge INTO — routing it
    through the fail-open loader (which _recorded_sprint_branch uses, because
    it runs BELOW the gate) would silently swallow the corruption."""

    def test_corrupt_sprint_propagates(self):
        _bf.write_system_context(self.smm_dir, stage=2)
        (self.smm_dir / "sprint.json").write_text("{not json")
        for call in (self._resolve, self._degrading, self._required):
            with self.assertRaises(sprint_store.SprintCorruptError):
                call()


class TestGetBaseCLI(_ResolverTestCase):
    """The chokepoint. `get-base` serves BOTH postures from one subcommand, so
    the fail-loud is opt-in: --required for the callers that branch from or
    merge into the answer, default-degrading for the ones that only probe.
    """

    def _get_base(self, *flags: str):
        cli = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
        return subprocess.run(
            [
                *[sys.executable, cli, "--smm-dir", str(self.smm_dir)],
                *["get-base", "--cwd", self.cwd, *flags],
            ],
            capture_output=True,
            text=True,
            env=_bf.GIT_ENV,
        )

    def _break_the_sprint_branch(self) -> None:
        """Stage 2, sprint exists, neither candidate branch does."""
        _bf.write_system_context(self.smm_dir, stage=2)
        _bf.write_sprint_json(self.smm_dir, "sprint-042", "ship it")
        sprint_store.set_branch(self.smm_dir, "test/sprint-042-deleted")

    def test_required_on_unresolvable_exits_1_with_empty_stdout(self):
        """Empty-stdout-on-failure is a HARD CONTRACT, not a nicety: the
        story-close preload does BASE=$(... get-base --required), and any byte
        on stdout becomes the ref it merges INTO. The reason goes to stderr,
        which is a separate stream precisely so a warning (log_hook_error
        mirrors to stderr even on the SUCCESS path) can never be spliced into a
        branch name."""
        self._break_the_sprint_branch()
        r = self._get_base("--required")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "", "stdout must be EMPTY on refusal")
        self.assertTrue(r.stderr.strip(), "the reason belongs on stderr")
        self.assertIn("sprint-042", r.stderr)

    def test_default_on_unresolvable_still_prints_primary_and_exits_0(self):
        """PINS the degrading contract xp-quality-review depends on for its
        diff range. Adding --required must not have changed the default."""
        self._break_the_sprint_branch()
        r = self._get_base()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "main")

    def test_required_on_resolvable_prints_the_sprint_branch(self):
        _bf.write_system_context(self.smm_dir, stage=2)
        _bf.make_branch(self.cwd, "test/sprint-042-ship-it")
        _bf.write_sprint_json(self.smm_dir, "sprint-042", "ship it")
        sprint_store.set_branch(self.smm_dir, "test/sprint-042-ship-it")
        r = self._get_base("--required")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "test/sprint-042-ship-it")

    def test_required_with_no_sprint_does_not_over_fire(self):
        """The over-fire canary at the CLI seam: --required must NOT raise for
        the legitimate degradations, or every no-sprint repo halts."""
        _bf.write_system_context(self.smm_dir, stage=2)
        r = self._get_base("--required")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "main")


if __name__ == "__main__":
    unittest.main()
