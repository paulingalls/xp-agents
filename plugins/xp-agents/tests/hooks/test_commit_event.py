#!/usr/bin/env python3
"""Direct-import tests for scripts/commit_event.py.

Exhaustive coverage of these behaviors already lives in
test_commit_handling.py and test_story_attribution.py, which reach them
through commit_handling.py's re-export. These tests pin that commit_event
is independently importable and behaves correctly when imported directly.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import commit_event
from _bases import _HookTestCase


class TestMakeCommitEventDirectImport(unittest.TestCase):
    def test_minimal_event(self):
        ev = commit_event.make_commit_event(
            "main",
            "fix: x",
            commit_hash="abc1234",
            files=["a.py"],
            code_file_count=1,
        )
        self.assertEqual(ev["type"], _common.COMMIT)
        self.assertEqual(ev["agent_id"], "main")
        self.assertEqual(ev["content"], "fix: x")
        self.assertEqual(ev["files"], ["a.py"])
        meta = ev["metadata"]
        self.assertEqual(meta["action"], "commit_success")
        self.assertTrue(meta["code_commit"])
        self.assertEqual(meta["code_file_count"], 1)
        self.assertEqual(meta["commit_hash"], "abc1234")


class TestResolveStoryIdDirectImport(_HookTestCase):
    def test_tier1_teammate_reads_assignment_file(self):
        import worktree

        assignment = worktree.story_assignment_path(self.smm_dir, "worktree-story-050")
        assignment.write_text("story-050")
        result = commit_event._resolve_story_id(
            self.smm_dir,
            "/proj/.claude/worktrees/worktree-story-050",
            ["src/app.py"],
        )
        self.assertEqual(result, "story-050")


if __name__ == "__main__":
    unittest.main()
