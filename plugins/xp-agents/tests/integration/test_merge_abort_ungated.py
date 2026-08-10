#!/usr/bin/env python3
"""E2E: `git merge --abort` must not trip the commit-cadence review gate
(story-001).

`is_git_commit` is the entry condition for the whole commit-path hook
stack. Before this story, `git merge --abort` answered yes, so an armed
gate blocked an operator trying to unwind a conflicted merge — worse than
a false block, because the escape hatch an operator reaches for next
(`git reset --hard HEAD`) discards the uncommitted work the abort would
have preserved. Drives the real gate in-process, per
test_review_cadence_e2e.py's pattern, rather than re-testing the
predicate in isolation.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import pre_tool_bash
from conftest import _IntegrationTestCase

_OVER_THRESHOLD = ("a.py", "b.py", "c.py")


class TestMergeAbortUngated(_IntegrationTestCase):
    def setUp(self):
        super().setUp()
        # Arm the gate: commit cadence blocks on 2+ changed code files with
        # no review recorded since.
        markers.write_review_cadence(self.smm_dir, "commit")

    def _run_gate(self, command: str) -> str | None:
        with (
            patch(
                "commits.get_code_files_for_review",
                return_value=list(_OVER_THRESHOLD),
            ),
            patch("commits.get_staged_diff", return_value=""),
        ):
            return pre_tool_bash.run(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": str(self.tmpdir),
                    "agent_id": "main",
                },
                smm_dir=self.smm_dir,
            )

    def test_control_plain_commit_is_blocked(self):
        """Control: proves the gate is actually armed, so the next
        assertion (merge --abort not blocking) is not vacuous."""
        with self.assertRaises(_common.BlockedError):
            self._run_gate("git commit -m wip")

    def test_merge_abort_does_not_block(self):
        self._run_gate("git merge --abort")  # must not raise

    def test_commit_compounded_with_merge_abort_still_blocks(self):
        """The bypass guard, end to end: appending `&& git merge --abort`
        to a real commit must not disarm the gate."""
        with self.assertRaises(_common.BlockedError):
            self._run_gate("git commit -m wip && git merge --abort")


if __name__ == "__main__":
    unittest.main()
