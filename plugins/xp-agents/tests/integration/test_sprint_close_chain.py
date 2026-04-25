#!/usr/bin/env python3
"""End-to-end capstone for sprint-032 / M-2 (story-005).

Pins the sprint-close chain end-to-end. Two scenarios:

1. **Chain integrity** — every node the chain requires (the close skill,
   its preload, the close-reviewer agent) is in place AND the close
   skill actually forks the close-reviewer. The narrower assertions
   (sprint-review references close, dispatch wiring, agent receives
   REVIEW_INPUT) live in test_sprint_close.py and
   test_subagent_tiers_sprint.py — this capstone only proves the parts
   compose, not the per-step contracts.

2. **Merge + cleanup sequencing** — given a sprint branch one commit
   ahead of the target, calling `merge_sprint_branch(target)` followed
   by `delete_branch` end-to-end leaves the target on a merge commit
   whose second parent is the sprint branch tip, and the sprint branch
   no longer exists locally. Proves the merge+delete primitives the
   close skill orchestrates actually work on real git state.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching
from _branching_fixtures import (
    get_current_branch,
    get_head_sha,
    init_repo,
    make_commit,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_SPRINT_CLOSE_SKILL = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "SKILL.md"
_SPRINT_CLOSE_PRELOAD = (
    _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"
)
_CLOSE_REVIEWER_AGENT = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"


class TestSprintReviewToCloseChainIntegrity(unittest.TestCase):
    """Capstone scenario 1: every chain node is wired and reachable."""

    @classmethod
    def setUpClass(cls):
        cls.close_text = _SPRINT_CLOSE_SKILL.read_text()
        cls.agent_text = _CLOSE_REVIEWER_AGENT.read_text()

    def test_close_skill_and_preload_exist(self):
        self.assertTrue(
            _SPRINT_CLOSE_SKILL.is_file(),
            "/xp-sprint-close SKILL.md must exist for the chain to land",
        )
        self.assertTrue(
            _SPRINT_CLOSE_PRELOAD.is_file(),
            "/xp-sprint-close preload.sh must exist (skill loader runs it)",
        )

    def test_close_skill_forks_close_reviewer(self):
        # The chain requires the close skill to invoke xp-close-reviewer.
        self.assertIn("xp-agents:xp-close-reviewer", self.close_text)

    def test_close_reviewer_agent_exists_and_is_read_only(self):
        # The agent's frontmatter must restrict tools to read-only —
        # no Edit/Write so a buggy fork can't mutate the repo.
        self.assertTrue(
            _CLOSE_REVIEWER_AGENT.is_file(),
            "xp-close-reviewer.md must exist for the close skill to fork",
        )
        # Guard against frontmatter-less files slicing garbage.
        self.assertTrue(
            self.agent_text.startswith("---"),
            "xp-close-reviewer.md must start with YAML frontmatter",
        )
        frontmatter = self.agent_text.split("---", 2)[1]
        self.assertNotIn("Edit", frontmatter)
        self.assertNotIn("Write", frontmatter)


class TestMergeAndCleanupEndToEnd(unittest.TestCase):
    """Capstone scenario 2: real merge + delete on a real git tree.

    Boots a temp repo, makes a sprint branch one commit ahead of the
    target, calls merge_sprint_branch + delete_branch (the merge+delete
    primitives the close skill orchestrates), and verifies the
    resulting tree state.
    """

    def test_merge_then_delete_lands_on_target(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            target_branch = get_current_branch(td)
            target_sha_before = get_head_sha(td)

            # merge_sprint_branch / delete_branch are stage-agnostic
            # primitives (they take target as an explicit arg and never
            # consult system_context.json) — no smm setup required.

            # Sprint branch one commit ahead of target.
            sprint_branch = "test/sprint-099-capstone"
            sprint_tip = make_commit(
                td, sprint_branch, "feature.txt", "sprint-only", "sprint feature"
            )

            # ACT: merge then delete (the primitives the close skill
            # orchestrates after the user confirms).
            branching.merge_sprint_branch(td, sprint_branch, target=target_branch)
            self.assertTrue(
                branching.delete_branch(td, sprint_branch),
                "delete_branch should report success",
            )

            # ASSERT: we are on the target branch.
            self.assertEqual(get_current_branch(td), target_branch)

            # ASSERT: target HEAD is a merge commit whose second parent
            # is the sprint branch tip.
            target_head = get_head_sha(td)
            self.assertNotEqual(
                target_head,
                target_sha_before,
                "target HEAD must have advanced after merge",
            )
            parents = (
                subprocess.run(
                    ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                    cwd=td,
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .split()
            )
            self.assertEqual(
                len(parents),
                3,
                f"--no-ff merge must produce 2 parents, got: {parents}",
            )
            self.assertIn(
                sprint_tip,
                parents[1:],
                "sprint branch tip must be one of the merge commit's parents",
            )

            # ASSERT: sprint branch no longer exists locally.
            self.assertFalse(
                branching.branch_exists(td, sprint_branch),
                "sprint branch must be gone after delete_branch",
            )


if __name__ == "__main__":
    unittest.main()
