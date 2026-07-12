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


if __name__ == "__main__":
    unittest.main()
