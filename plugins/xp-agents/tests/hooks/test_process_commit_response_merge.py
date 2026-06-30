#!/usr/bin/env python3
"""Merge-commit review-cycle reset pin (sprint-104 story-005 Fix A).

A `--no-ff` merge commit lands via `close_common.cmd_merge()` →
`append_merge_commit_event()`. The merge appends a commit event but
previously did NOT call `markers.reset_review_cycle()` — the parent
Bash PreToolUse hook only matches top-level `git commit` shells, so
the per-commit `commit_handling.py:reset_review_cycle()` was bypassed.
The prior commit's `quality_review_done=True` marker persisted across
the merge, latching the review gate for the next solo commit on the
sprint branch.

These tests pin that `append_merge_commit_event()` now resets the
review cycle in addition to emitting the event. Resolves event
1c15356973d7 (deferred 4 sessions across retros).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from merge_commit_event import append_merge_commit_event


def _init_repo(repo: Path) -> str:
    """Initialize a git repo with an initial commit; return HEAD sha."""
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("init\n")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Merge sprint-104/story-A\n\nBody"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


def _seed_smm(repo: Path) -> Path:
    """Create an SMM dir alongside the repo and seed an empty event log."""
    smm = repo / ".smm"
    smm.mkdir(parents=True, exist_ok=True)
    (smm / "events.jsonl").write_text("")
    return smm


class TestMergeCommitResetsReviewCycle(unittest.TestCase):
    """Pin that append_merge_commit_event resets the review cycle.

    Fix A for sprint-104 story-005 (resolves 1c15356973d7).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve()
        self.head_sha = _init_repo(self.repo)
        self.smm = _seed_smm(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def test_merge_commit_resets_review_cycle_for_main_agent(self):
        """Stale quality_review_done=True is cleared after the merge event.

        Pre-Fix-A: the merge appended the commit event but left the
        prior review-cycle flags intact → the next solo commit on the
        sprint branch hit a falsely-latched gate.
        """
        agent_id = "main"
        # Arrange: prior cycle is dirty — quality_review_done=True.
        markers.write_review_cycle(
            self.smm,
            agent_id,
            {
                "last_review_commit": "deadbeefcafe",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )
        prior = markers.read_review_cycle(self.smm, agent_id)
        self.assertTrue(prior["quality_review_done"])

        # Act: append a merge commit event the same way cmd_merge does.
        append_merge_commit_event(
            str(self.repo), self.smm, "paulingalls/story-A-something"
        )

        # Assert: the review cycle is reset; last_review_commit now points
        # at the merge HEAD; quality_review_done is False (or absent).
        cycle = markers.read_review_cycle(self.smm, agent_id)
        self.assertEqual(
            cycle.get("last_review_commit"),
            self.head_sha,
            "merge HEAD must become the new last_review_commit",
        )
        self.assertFalse(
            cycle.get("quality_review_done", False),
            "quality_review_done must reset to False on merge",
        )
        self.assertFalse(
            cycle.get("simplify_done", False),
            "simplify_done must reset to False on merge",
        )

    def test_merge_commit_event_still_appended(self):
        """Regression pin: the merge-commit event emission is unchanged.

        Fix A adds a reset call alongside the event emission; the event
        itself must still land (commit_handling.make_commit_event shape).
        """
        agent_id = "main"
        markers.write_review_cycle(
            self.smm,
            agent_id,
            {
                "last_review_commit": "deadbeefcafe",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )

        append_merge_commit_event(
            str(self.repo), self.smm, "paulingalls/story-A-something"
        )

        events_text = (self.smm / "events.jsonl").read_text()
        self.assertIn('"type": "commit"', events_text)
        self.assertIn(self.head_sha, events_text)
        self.assertIn('"is_merge": true', events_text)

    def test_merge_with_no_smm_dir_is_noop(self):
        """Existing graceful-degradation: smm_dir=None short-circuits.

        Preserves the pre-Fix-A behavior for in-process tests that call
        cmd_merge without threading --smm-dir.
        """
        # No exception, no state change. Just confirm the call returns cleanly.
        append_merge_commit_event(str(self.repo), None, "paulingalls/story-A")
        # Nothing to assert state-wise — the function is a no-op.

    def test_merge_resets_cycle_keyed_per_agent(self):
        """A subagent's separate review cycle is unaffected by main's merge.

        Per-agent cycles are isolated via the marker keying. The merge
        runs in the orchestrator cwd ("main"); a teammate's cycle must
        not be inadvertently cleared.
        """
        markers.write_review_cycle(
            self.smm,
            "main",
            {
                "last_review_commit": "deadbeefcafe",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )
        markers.write_review_cycle(
            self.smm,
            "worktree-story-zzz",
            {
                "last_review_commit": "feedface1111",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )

        append_merge_commit_event(str(self.repo), self.smm, "paulingalls/story-A-thing")

        # main reset
        self.assertFalse(
            markers.read_review_cycle(self.smm, "main")["quality_review_done"]
        )
        # teammate untouched
        teammate = markers.read_review_cycle(self.smm, "worktree-story-zzz")
        self.assertTrue(teammate["quality_review_done"])
        self.assertEqual(teammate["last_review_commit"], "feedface1111")


if __name__ == "__main__":
    unittest.main()
