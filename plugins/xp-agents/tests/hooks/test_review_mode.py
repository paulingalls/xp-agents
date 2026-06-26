#!/usr/bin/env python3
"""Tests for the xp-quality-review review_mode preload helper.

MODE is the role-lever discriminator: a fresh /code-review completion this
review cycle (simplify_done set for the resolved agent_id) => consume-findings;
otherwise => self-find. agent_id is resolved from --cwd exactly as the
per-commit gate resolves it, so the read keys match the writer.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "scripts"
    ),
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
import review_mode
from conftest import _SMMTestCase

_WT = "/proj/.claude/worktrees/worktree-story-001"


class TestReviewMode(_SMMTestCase):
    def _run(self, cwd: str = ".") -> str:
        argv = ["review_mode", "--smm-dir", str(self.smm_dir), "--cwd", cwd]
        buf = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(buf):
            review_mode.main()
        return buf.getvalue().strip()

    def test_no_review_is_self_find(self):
        self.assertEqual(self._run("."), "self-find")

    def test_fresh_code_review_is_consume_findings(self):
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        self.assertEqual(self._run("."), "consume-findings")

    def test_quality_review_alone_is_self_find(self):
        """A standalone self-find review sets quality_review_done WITHOUT
        simplify_done — still self-find (no /code-review findings to consume)."""
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.assertEqual(self._run("."), "self-find")

    def test_worktree_cwd_resolves_agent_id(self):
        """simplify_done under the worktree id + worktree cwd => consume-findings;
        proves the helper resolves agent_id from cwd (not bare 'main')."""
        markers.set_review_flag(self.smm_dir, "worktree-story-001", "simplify_done")
        self.assertEqual(self._run(_WT), "consume-findings")
        # The 'main' scope is untouched, so a '.' cwd still reads self-find.
        self.assertEqual(self._run("."), "self-find")


if __name__ == "__main__":
    unittest.main()
