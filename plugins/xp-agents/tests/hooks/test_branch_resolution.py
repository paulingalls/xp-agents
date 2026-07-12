#!/usr/bin/env python3
"""Tests for branch_resolution.py — SMM-state -> branch/stage answers.

Home for all resolver coverage: the stage machinery, the recorded-name
lookups, and the story-base resolution that /xp-assign, /xp-schedule and
/xp-story-close branch from or merge into.

test_branching.py and test_branching_plan.py are both already over the
500-line cap; new resolver coverage lands here, not there.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branch_resolution
import branching


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


if __name__ == "__main__":
    unittest.main()
