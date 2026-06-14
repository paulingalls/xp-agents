#!/usr/bin/env python3
"""Capstone E2E: the review-cadence loop (story-007).

End-to-end proof that Milestone 1's pieces compose: one .review-cadence
marker drives BOTH the per-commit gate (pre_tool_bash) AND the story-close
routing (preload REVIEW_PATH) consistently. In story cadence, over-threshold
commits proceed with a deferral advisory and the review runs once at
story-close (full-cycle); in commit cadence the per-commit gate blocks
(default path intact).

Consumes the already-merged story-001..006 surfaces; changes no production
code.
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
import session_start
from _bases import _PLUGIN_ROOT
from conftest import _extract_preload_var, _IntegrationTestCase

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "scripts" / "preload.sh"
_COMMIT_CMD = "git commit -m wip"
_OVER_THRESHOLD = ("a.py", "b.py", "c.py")


class TestReviewCadenceE2E(_IntegrationTestCase):
    """The cadence marker is the single switch across gate + story-close."""

    def _set_cadence(self, value: str) -> None:
        markers.write_review_cadence(self.smm_dir, value)

    def _commit_gate(self) -> str | None:
        """Drive the per-commit gate at the over-threshold review point."""
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
                    "tool_input": {"command": _COMMIT_CMD},
                    "cwd": str(self.tmpdir),
                    "agent_id": "main",
                },
                smm_dir=self.smm_dir,
            )

    def _review_path(self) -> str | None:
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return _extract_preload_var(result.stdout, "REVIEW_PATH")

    def test_story_cadence_commits_not_blocked_with_advisory(self):
        """AC#1: two over-threshold commits proceed, each with the advisory."""
        self._set_cadence("story")
        for _ in range(2):
            result = self._commit_gate()  # must not raise
            self.assertIsNotNone(result)
            self.assertIn("/xp-story-close", result or "")

    def test_story_cadence_close_routes_full_cycle(self):
        """AC#2: story-close preload routes to the full review cycle."""
        self._set_cadence("story")
        self.assertEqual(self._review_path(), "full-cycle")

    def test_commit_cadence_gate_blocks(self):
        """AC#3: default (commit) cadence still blocks the commit for review."""
        self._set_cadence("commit")
        with self.assertRaises(_common.BlockedError) as ctx:
            self._commit_gate()
        self.assertIn("/code-review", str(ctx.exception))

    def test_e2e_story_loop_reviews_once_at_close(self):
        """AC#4: the marker is the single switch — story defers to one review
        at the merge boundary; commit blocks per-commit (contrast)."""
        # story cadence: commits flow (no review marker set), close is full-cycle.
        self._set_cadence("story")
        self.assertIn("/xp-story-close", self._commit_gate() or "")
        self.assertIn("/xp-story-close", self._commit_gate() or "")
        self.assertEqual(self._review_path(), "full-cycle")
        # commit cadence: the same gate blocks, and close keeps the reviewer fork.
        self._set_cadence("commit")
        with self.assertRaises(_common.BlockedError):
            self._commit_gate()
        self.assertEqual(self._review_path(), "close-reviewer")

    def test_e2e_fresh_start_resets_cadence_across_both_surfaces(self):
        """AC#4: a fresh start (story-003) is the kickoff leg of the loop — it
        resets a prior session's 'story' cadence to the careful 'commit'
        default, and that single reset flips BOTH downstream surfaces: the
        per-commit gate goes back to blocking and story-close re-forks the
        reviewer. No sibling composes session_start into the gate + preload."""
        self._set_cadence("story")
        # A fresh start (startup) is the only leg that re-anchors the session;
        # run it in-process like the other surfaces so the reset is observed,
        # not stubbed.
        session_start.run(
            {"session_id": "e2e", "source": "startup"}, smm_dir=self.smm_dir
        )
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")
        # The reset cadence now drives both surfaces back to the careful path.
        with self.assertRaises(_common.BlockedError):
            self._commit_gate()
        self.assertEqual(self._review_path(), "close-reviewer")


if __name__ == "__main__":
    unittest.main()
