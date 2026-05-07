#!/usr/bin/env python3
"""Pin the _IntegrationTestCase per-test worktree cleanup contract.

Sprint-069's closing-state capstone worked around an unaddressed leak
in _IntegrationTestCase by hand-picking unique story-ids per test
(story-A1/B1/C1/D1/E1/E2). Without per-test cleanup, a test that
creates a worktree at `.claude/worktrees/worktree-story-X` registers
it in the class-shared tmpdir's git registry; a sibling test reusing
the same id then trips `git worktree add` (path already registered).

This test pins that _IntegrationTestCase.tearDown prunes
`.claude/worktrees/worktree-*` worktrees so reuse-by-id is safe and
future closing-state tests don't have to invent fresh ids.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "smm"))

from _worktree_fixtures import make_teammate_worktree
from conftest import _IntegrationTestCase


def _list_worktrees(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return [
        line.split("worktree ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


class TestIntegrationTestCaseTearDownPrunesWorktrees(_IntegrationTestCase):
    """Verifies _IntegrationTestCase.tearDown removes story worktrees."""

    def test_teardown_removes_worktrees_created_during_test(self):
        # Create a worktree the way real integration tests do.
        wt = make_teammate_worktree(self.tmpdir, "story-prune-1", "u/prune-1")
        self.assertTrue(wt.exists(), "worktree dir must exist before tearDown")
        wts_before = _list_worktrees(self.tmpdir)
        self.assertTrue(
            any("worktree-story-prune-1" in w for w in wts_before),
            f"setUp/test must register worktree; got {wts_before!r}",
        )

        # Invoke tearDown explicitly — this is the contract under test.
        self.tearDown()

        wts_after = _list_worktrees(self.tmpdir)
        self.assertFalse(
            any("worktree-story-prune-1" in w for w in wts_after),
            f"tearDown must prune worktree; got {wts_after!r}",
        )

    def test_teardown_safe_when_no_worktrees_created(self):
        # Defensive: tearDown without any worktrees must not raise.
        self.tearDown()  # Should be a no-op, no exception.


if __name__ == "__main__":
    unittest.main()
