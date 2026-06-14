#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: story-cadence commit-gate relaxation.

Split from test_pre_tool_bash_gates.py — story-002. In 'story' cadence the
per-commit review-cycle block becomes a one-line advisory naming
/xp-story-close; tier-1 security and ruff stay unconditional.
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
from conftest import _HookTestCase, _make_bash_input

_COMMIT_CMD = "git commit -m 'test'"
_CODE_FILES_PATCH = "commits.get_code_files_for_review"

# A staged diff carrying a tier-1 secret (mirrors test_pre_tool_bash.py).
_AKIA_DIFF = (
    "diff --git a/src/cfg.py b/src/cfg.py\n"
    "--- a/src/cfg.py\n"
    "+++ b/src/cfg.py\n"
    "@@ -1,1 +1,2 @@\n"
    " existing\n"
    '+aws_key = "AKIAIOSFODNN7EXAMPLE"\n'
)


_OVER_THRESHOLD = ("a.py", "b.py", "c.py")


class TestStoryCadenceCommitGate(_HookTestCase):
    """story-002: 'story' cadence relaxes the review-cycle block to an advisory."""

    def test_story_cadence_skips_block_with_advisory(self):
        """AC#1: 'story' cadence, over threshold, no reviews → advisory, no block."""
        markers.write_review_cadence(self.smm_dir, "story")
        with patch(_CODE_FILES_PATCH, return_value=list(_OVER_THRESHOLD)):
            result = pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
        self.assertIsNotNone(result)
        self.assertIn("/xp-story-close", result or "")

    def test_commit_cadence_still_blocks(self):
        """AC#2: default ('commit') cadence still blocks for /code-review."""
        with (
            patch(_CODE_FILES_PATCH, return_value=list(_OVER_THRESHOLD)),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
        self.assertIn("/code-review", str(ctx.exception))

    @patch("commits.get_staged_diff")
    def test_story_cadence_security_still_blocks(self, mock_diff):
        """AC#3: relaxation is review-only — tier-1 security still blocks."""
        mock_diff.return_value = _AKIA_DIFF
        markers.write_review_cadence(self.smm_dir, "story")
        with (
            patch(_CODE_FILES_PATCH, return_value=list(_OVER_THRESHOLD)),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_bash.run(
                _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
            )
        self.assertIn("aws-access-key", str(ctx.exception))

    def test_e2e_story_cadence_over_threshold_proceeds(self):
        """AC#4 E2E: story-cadence over-threshold commit proceeds with advisory."""
        markers.write_review_cadence(self.smm_dir, "story")
        with patch(_CODE_FILES_PATCH, return_value=list(_OVER_THRESHOLD)):
            try:
                result = pre_tool_bash.run(
                    _make_bash_input(command=_COMMIT_CMD), smm_dir=self.smm_dir
                )
            except _common.BlockedError as e:
                self.fail(f"story cadence must not block the commit: {e}")
        self.assertIsNotNone(result)
        self.assertIn("/xp-story-close", result or "")


if __name__ == "__main__":
    unittest.main()
