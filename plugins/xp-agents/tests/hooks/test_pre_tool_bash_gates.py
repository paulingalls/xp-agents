#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: review-cycle gate and accept gate.

Split from test_pre_tool_bash.py -- keeps gate-related test classes separate.
Further split into test_pre_tool_bash_gates_decision_nudge.py (decision-time
nudges) and test_pre_tool_bash_gates_branch_protection.py (branch/cwd gates).
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
)

_COMMIT_CMD = "git commit -m 'test'"


class TestPreToolBashReviewCycle(_HookTestCase):
    """Tests for commit-gated review cycle in pre_tool_bash.py."""

    _CODE_FILES_PATCH = "commits.get_code_files_for_review"

    def test_above_threshold_blocks_without_quality_review(self):
        """3+ code files, no flags set -> blocks for /xp-quality-review.

        Per-increment review is now /xp-quality-review only (xp-code-reviewer
        self-finds correctness); /code-review no longer gates a commit."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-quality-review", str(ctx.exception))
            self.assertNotIn("/code-review", str(ctx.exception))

    def test_simplify_done_alone_still_blocks(self):
        """simplify_done=True but quality_review_done=False -> still blocks.

        simplify_done no longer satisfies the per-commit gate; only
        quality_review_done clears it."""
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            with self.assertRaises(_common.BlockedError) as ctx:
                pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            self.assertIn("/xp-quality-review", str(ctx.exception))

    def test_above_threshold_passes_quality_review_only(self):
        """quality_review_done=True alone -> commit allowed (simplify_done
        not required)."""
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_below_threshold_passes(self):
        """M-4: below-threshold commits (<3 code files) skip the review-cycle
        gate entirely. /security-review covers the cumulative diff at
        /xp-{free,sprint,plan}-close Step 4.5."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_zero_code_files_passes(self):
        """No code files changed -> commit allowed."""
        with patch(self._CODE_FILES_PATCH, return_value=[]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )

    def test_xp_agent_skips(self):
        """xp- agents bypass the review cycle gate."""
        with patch(self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD, agent_type="xp-housekeeper"),
                smm_dir=self.smm_dir,
            )

    def test_uses_last_review_commit(self):
        """Gate reads last_review_commit from marker."""
        markers.reset_review_cycle(self.smm_dir, "main", "abc123")
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        with patch(
            self._CODE_FILES_PATCH, return_value=["a.py", "b.py", "c.py"]
        ) as mock:
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
            # Verify the commit hash was passed to get_code_files_for_review
            self.assertEqual(mock.call_args[0][1], "abc123")


class TestAcceptGate(_HookTestCase):
    """Accept gate blocks update-story done without /xp-accept."""

    _SPRINT_CMD = (
        "python3 /path/to/sprint_cli.py --smm-dir /tmp/smm update-story story-001 done"
    )

    def test_update_story_done_with_marker_blocks(self):
        """update-story done with ACCEPT marker should block."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=self._SPRINT_CMD),
                smm_dir=self.smm_dir,
            )

    def test_shipped_continuation_shape_with_marker_blocks(self):
        """/xp-accept Step 4 wraps the invocation across a shell line-continuation.

        The ACCEPT gate matched that shape for free while its regex looked only for
        `update-story <id> done`. Requiring `sprint_cli` on the SAME line (the merge
        gate's tightening, which this gate now shares) silently drops it — and this
        is the ONE shape production actually runs.
        """
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        shipped = (
            "python3 ${CLAUDE_PLUGIN_ROOT}/smm/sprint_cli.py --smm-dir /tmp/smm \\\n"
            "  update-story story-001 done"
        )
        with self.assertRaises(_common.BlockedError):
            pre_tool_bash.run(
                _make_bash_input(command=shipped),
                smm_dir=self.smm_dir,
            )

    def test_update_story_done_without_marker_allows(self):
        """update-story done without ACCEPT marker should allow."""
        result = pre_tool_bash.run(
            _make_bash_input(command=self._SPRINT_CMD),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_update_story_in_progress_with_marker_allows(self):
        """update-story in-progress should not be blocked."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        cmd = self._SPRINT_CMD.replace("done", "in-progress")
        result = pre_tool_bash.run(
            _make_bash_input(command=cmd),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_non_sprint_command_with_marker_allows(self):
        """Regular command should not be blocked by ACCEPT marker."""
        markers.marker_write(self.smm_dir, markers.ACCEPT, "done")
        result = pre_tool_bash.run(
            _make_bash_input(command="python3 -m unittest -v"),
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
