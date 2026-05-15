#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: worktree agent ID for commit gate markers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from unittest.mock import patch

import _common
import markers
import pre_tool_bash
from conftest import _HookTestCase, _make_bash_input

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashWorktreeAgentId(_HookTestCase):
    """Commit gate reads markers under worktree-derived agent_id."""

    def test_worktree_cwd_reads_correct_markers(self):
        """Worktree cwd resolves agent_id for commit gate markers.

        With only simplify_done set under the worktree-derived agent_id,
        the gate must block on /xp-quality-review (proves it read the
        worktree-scoped marker, not main's empty cycle).
        """
        markers.set_review_flag(self.smm_dir, "teammate-story-001", "simplify_done")
        inp = _make_bash_input(
            command=_COMMIT_CMD,
            cwd="/proj/.claude/worktrees/teammate-story-001",
            agent_id="",
        )
        with patch(
            "commits.get_code_files_for_review",
            return_value=["a.py", "b.py", "c.py"],
        ):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(inp, smm_dir=self.smm_dir)
            self.assertIn("/xp-quality-review", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
