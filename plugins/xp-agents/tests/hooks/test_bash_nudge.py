#!/usr/bin/env python3
"""Tests for mid-chain nudge in PostToolUse:Bash commit handling.

The nudge fires when the main agent commits during solo mode with 2+
in-progress stories, reminding it to self-assess whether to switch
branches. Advisory only (additionalContext), not a block.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, _s, _sprint_json

COMMIT_CMD = 'git commit -m "fix thing"'
COMMIT_STDOUT = "[main abc123] fix thing\n 1 file changed, 1 insertion(+)"


def _two_in_progress_sprint() -> str:
    return _sprint_json(
        [
            _s("story-001", "Add nudge", "in-progress"),
            _s("story-002", "Add auto-switch", "in-progress"),
        ],
        sprint_id="sprint-047",
    )


def _one_in_progress_sprint() -> str:
    return _sprint_json(
        [_s("story-001", "Add nudge", "in-progress")],
        sprint_id="sprint-047",
    )


class TestMidChainNudge(_HookTestCase):
    def _run_commit(self, **input_overrides):
        inp = _make_bash_input(
            command=COMMIT_CMD, stdout=COMMIT_STDOUT, **input_overrides
        )
        with patch_commits():
            return bash_post_tool.run(inp, smm_dir=self.smm_dir)

    def test_solo_two_in_progress_returns_nudge(self):
        (self.smm_dir / "sprint.json").write_text(_two_in_progress_sprint())
        result = self._run_commit()
        self.assertIsNotNone(result)
        self.assertIn("Multiple stories in-progress", result)

    def test_solo_one_in_progress_no_nudge(self):
        (self.smm_dir / "sprint.json").write_text(_one_in_progress_sprint())
        result = self._run_commit()
        if result is not None:
            self.assertNotIn("Multiple stories in-progress", result)

    def test_teammate_no_nudge(self):
        (self.smm_dir / "sprint.json").write_text(_two_in_progress_sprint())
        result = self._run_commit(
            cwd="/proj/.claude/worktrees/worktree-story-001/repo",
            agent_id="",
        )
        if result is not None:
            self.assertNotIn("Multiple stories in-progress", result)

    def test_xp_agent_no_nudge(self):
        (self.smm_dir / "sprint.json").write_text(_two_in_progress_sprint())
        inp = _make_bash_input(
            command=COMMIT_CMD,
            stdout=COMMIT_STDOUT,
            agent_type="xp-quality-review",
        )
        with patch_commits():
            result = bash_post_tool.run(inp, smm_dir=self.smm_dir)
        if result is not None:
            self.assertNotIn("Multiple stories in-progress", result)

    def test_no_sprint_no_nudge(self):
        result = self._run_commit()
        if result is not None:
            self.assertNotIn("Multiple stories in-progress", result)

    def test_canonical_wording_pinned(self):
        """Pin the exact nudge text so accidental rewording is caught."""
        (self.smm_dir / "sprint.json").write_text(_two_in_progress_sprint())
        result = self._run_commit()
        self.assertIsNotNone(result)
        self.assertIn(bash_post_tool.MID_CHAIN_NUDGE, result)


if __name__ == "__main__":
    unittest.main()
