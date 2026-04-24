#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: worktree agent ID and resolves trailer nudge.

Split from test_pre_tool_bash_gates.py to keep files under 500 lines.
"""

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
from conftest import (
    _HookTestCase,
    _make_bash_input,
    _ProbeTestHelpers,
    make_event,
)

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashWorktreeAgentId(_HookTestCase):
    """Commit gate reads markers under worktree-derived agent_id."""

    def test_worktree_cwd_reads_correct_markers(self):
        """Worktree cwd resolves agent_id for commit gate markers."""
        markers.set_review_flag(self.smm_dir, "teammate-story-001", "simplify_done")
        markers.set_review_flag(
            self.smm_dir, "teammate-story-001", "quality_review_done"
        )
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
            self.assertIn("/xp-security-triage", str(ctx.exception))


class TestResolvesTrailerNudge(_ProbeTestHelpers, _HookTestCase):
    """Pre-commit nudge when staged files overlap open concerns."""

    def _write_concern(self, content: str, files: list[str]) -> str:
        event = make_event("concern", content=content, severity="medium", files=files)
        self._write_events([event])
        return event["id"]

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_nudge_when_staged_overlaps_concern(self, *_mocks):
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Resolves-Event", result)

    @patch("commits.get_staged_files", return_value=["scripts/other.py"])
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_no_concern_nudge_when_no_overlap(self, *_mocks):
        """No concern-specific nudge, but trailer reminder still appears."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        result = pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("auth bypass", result)
        self.assertIn("Resolves-Event:", result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_no_nudge_when_trailer_present(self, *_mocks):
        cid = self._write_concern("auth bypass risk", ["scripts/auth.py"])
        cmd = f'git commit -m "fix auth\n\nResolves-Event: {cid}"'
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    def test_no_nudge_on_non_commit(self, *_mocks):
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        result = pre_tool_bash.run(
            _make_bash_input(command="ls -la"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    @patch("commits.get_staged_files", return_value=["scripts/auth.py"])
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_probe_status_event_emitted(self, *_mocks):
        """Pre-commit emits probe status event when candidates found."""
        cid = self._write_concern("auth bypass risk", ["scripts/auth.py"])
        pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertEqual(len(self._probes()), 1)
        self.assertEqual(self._probes()[0]["metadata"]["probe_candidates"], [cid])

    @patch("commits.get_staged_files", return_value=["scripts/other.py"])
    @patch("security.is_git_commit", return_value=True)
    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("security.has_staged_code_files", return_value=False)
    def test_no_probe_status_event_when_no_overlap(self, *_mocks):
        """No probe status event when staged files don't overlap concerns."""
        self._write_concern("auth bypass risk", ["scripts/auth.py"])
        pre_tool_bash.run(
            _make_bash_input(command=_COMMIT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertEqual(len(self._probes()), 0)


if __name__ == "__main__":
    unittest.main()
