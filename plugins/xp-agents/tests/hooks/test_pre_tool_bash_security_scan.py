#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: Tier 1 deterministic security scan.

Split from test_pre_tool_bash.py -- keeps the security-scan gate separate.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
)
from markers import write_review_cycle


class TestTier1SecurityScan(_HookTestCase):
    """Story-003: Tier 1 deterministic scan must run before the review-cycle gate."""

    _AKIA_DIFF = (
        "diff --git a/src/cfg.py b/src/cfg.py\n"
        "--- a/src/cfg.py\n"
        "+++ b/src/cfg.py\n"
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        '+aws_key = "AKIAIOSFODNN7EXAMPLE"\n'
    )
    _CLEAN_DIFF = (
        "diff --git a/src/cfg.py b/src/cfg.py\n"
        "--- a/src/cfg.py\n"
        "+++ b/src/cfg.py\n"
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        '+greeting = "hello"\n'
    )

    def _commit_input(self, command: str = "git commit -m 'fix'") -> dict:
        return _make_bash_input(command=command)

    def _satisfy_review_cycle(self) -> None:
        """Write all markers so the existing review-cycle gate would pass."""
        write_review_cycle(
            self.smm_dir,
            "main",
            {
                "last_review_commit": "",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )

    @patch("commits.get_staged_diff")
    def test_tier1_blocks_aws_key_in_staged_diff(self, mock_diff):
        """AC #1: staged AKIA literal raises BlockedError naming pattern + file:line."""
        mock_diff.return_value = self._AKIA_DIFF
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("aws-access-key", msg)
        self.assertIn("src/cfg.py", msg)

    @patch("commits.get_staged_diff")
    def test_tier1_passes_clean_diff(self, mock_diff):
        """AC #2: a clean staged diff does not raise a Tier 1 BlockedError."""
        mock_diff.return_value = self._CLEAN_DIFF
        # May still return an additional-context string (e.g. trailer reminder),
        # but must not raise BlockedError from Tier 1.
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"Clean diff should not block; got: {e}")

    @patch("commits.get_staged_diff")
    def test_tier1_skipped_for_non_commit(self, mock_diff):
        """AC #3: non-commit Bash does not invoke the Tier 1 scanner."""
        pre_tool_bash.run(
            self._commit_input(command="git status"),
            smm_dir=self.smm_dir,
        )
        mock_diff.assert_not_called()

    @patch("commits.get_staged_diff")
    def test_tier1_blocks_even_when_review_cycle_satisfied(self, mock_diff):
        """AC #4 capstone: Tier 1 fires even with all review-cycle flags green."""
        mock_diff.return_value = self._AKIA_DIFF
        self._satisfy_review_cycle()
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("aws-access-key", msg)
        self.assertIn("src/cfg.py:2", msg)

    @patch("commits.get_staged_diff")
    def test_tier1_fails_closed_on_git_failure(self, mock_diff):
        """git diff failure (None) must block, not silently bypass Tier 1."""
        mock_diff.return_value = None
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("git diff", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
