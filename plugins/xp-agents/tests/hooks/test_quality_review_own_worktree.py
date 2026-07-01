#!/usr/bin/env python3
"""Tests for the /xp-quality-review own-worktree precedence resolver.

Regression guard for the parallel-teammate CWD-misdetect (risk 840c951b31e4,
concern 99e705d9dc40): a teammate self-reviewing from its OWN worktree must
review its own diff, not whatever story is `closing` in shared sprint state.

The precedence lives in worktree.resolve_review_worktree (own-worktree first,
else the global closing-scan) so the ordering is a testable Python seam, not
just shell call-order in preload.sh.
"""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree
from conftest import _HookTestCase

_DUMMY_SMM = Path("/tmp/nonexistent-smm-for-tests")


class TestResolveOwnTeammateWorktree(_HookTestCase):
    def test_none_in_main_checkout(self):
        """A main-checkout cwd (no worktree fragment) resolves to None."""
        self.assertIsNone(worktree.resolve_own_teammate_worktree("/repo/main/checkout"))

    def test_none_on_empty_cwd(self):
        self.assertIsNone(worktree.resolve_own_teammate_worktree(""))

    def test_worktree_root_cwd(self):
        cwd = "/repo/.claude/worktrees/worktree-story-005"
        result = self._assert_not_none(worktree.resolve_own_teammate_worktree(cwd))
        self.assertEqual(Path(result[0]).name, "worktree-story-005")

    def test_nested_subdir_resolves_root(self):
        """A cwd nested under the worktree still resolves the worktree root."""
        cwd = "/repo/.claude/worktrees/worktree-story-005/plugins/xp-agents"
        result = self._assert_not_none(worktree.resolve_own_teammate_worktree(cwd))
        self.assertEqual(Path(result[0]).name, "worktree-story-005")

    def test_non_story_worktree_not_a_teammate(self):
        """A non-story `worktree-*` cwd is NOT a teammate worktree — the gate
        keys on the `worktree-story-` prefix, agreeing with
        identity.is_worktree_teammate (which would also reject it)."""
        cwd = "/repo/.claude/worktrees/worktree-plan-x/src"
        self.assertIsNone(worktree.resolve_own_teammate_worktree(cwd))


class TestResolveReviewWorktreePrecedence(_HookTestCase):
    def test_own_worktree_wins_over_a_different_closing_story(self):
        """Precedence: own worktree resolves WITHOUT consulting the closing-scan."""
        cwd = "/repo/.claude/worktrees/worktree-story-005/sub"
        with mock.patch.object(
            worktree,
            "find_closing_teammate_worktree",
            return_value=("/repo/.claude/worktrees/worktree-story-001", "br-001"),
        ) as m_closing:
            result = self._assert_not_none(
                worktree.resolve_review_worktree(_DUMMY_SMM, cwd)
            )
        self.assertEqual(Path(result[0]).name, "worktree-story-005")
        m_closing.assert_not_called()  # own identity short-circuits the global scan

    def test_main_checkout_falls_back_to_closing_scan(self):
        """Orchestrator cwd (no own worktree) uses the closing-scan, unchanged."""
        closing = ("/repo/.claude/worktrees/worktree-story-001", "br-001")
        with mock.patch.object(
            worktree, "find_closing_teammate_worktree", return_value=closing
        ) as m_closing:
            result = worktree.resolve_review_worktree(_DUMMY_SMM, "/repo/main")
        self.assertEqual(result, closing)
        m_closing.assert_called_once()

    def test_main_checkout_no_closing_story_returns_none(self):
        with mock.patch.object(
            worktree, "find_closing_teammate_worktree", return_value=None
        ):
            result = worktree.resolve_review_worktree(_DUMMY_SMM, "/repo/main")
            self.assertIsNone(result)


if __name__ == "__main__":
    import unittest

    unittest.main()
