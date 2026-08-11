#!/usr/bin/env python3
"""Merge-commit review-cycle reset pin (sprint-104 story-005 Fix A).

A `--no-ff` merge commit lands via `close_common.cmd_merge()` →
`append_merge_commit_event()`. The merge appends a commit event but
previously did NOT call `review_records.clear_review_flags()` — the parent
Bash PreToolUse hook only matches top-level `git commit` shells, so
the per-commit `commit_handling.py`'s own clear was bypassed.
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

import review_records

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import resolution
from event_schema import EVENT_TYPE_COMMIT
from merge_commit_event import append_merge_commit_event


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


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
        review_records.write_review_flags(
            self.smm,
            agent_id,
            {"simplify_done": True, "quality_review_done": True},
        )
        prior = review_records.read_review_flags(self.smm, agent_id)
        self.assertTrue(prior["quality_review_done"])

        # Act: append a merge commit event the same way cmd_merge does.
        append_merge_commit_event(
            str(self.repo), self.smm, "paulingalls/story-A-something"
        )

        # Assert: the flags are cleared and the watermark advances to the
        # merge HEAD — two records, both written by the merge.
        cycle = review_records.read_review_flags(self.smm, agent_id)
        self.assertEqual(
            review_records.read_review_watermark(self.smm, agent_id),
            self.head_sha,
            "merge HEAD must become the new watermark",
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
        review_records.write_review_flags(
            self.smm,
            agent_id,
            {"simplify_done": True, "quality_review_done": True},
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
        review_records.write_review_flags(
            self.smm,
            "main",
            {"simplify_done": True, "quality_review_done": True},
        )
        review_records.write_review_flags(
            self.smm,
            "worktree-story-zzz",
            {"simplify_done": True, "quality_review_done": True},
        )
        review_records.write_review_watermark(
            self.smm, "worktree-story-zzz", "feedface1111"
        )

        append_merge_commit_event(str(self.repo), self.smm, "paulingalls/story-A-thing")

        # main reset
        self.assertFalse(
            review_records.read_review_flags(self.smm, "main")["quality_review_done"]
        )
        # teammate untouched
        teammate = review_records.read_review_flags(self.smm, "worktree-story-zzz")
        self.assertTrue(teammate["quality_review_done"])
        self.assertEqual(
            review_records.read_review_watermark(self.smm, "worktree-story-zzz"),
            "feedface1111",
        )


class TestMergeCommitRelinksResolvesEvent(unittest.TestCase):
    """Story-008 leg (b): the merge-fallback event must carry the merged-in
    commits' `Resolves-Event:` trailers, not omit `metadata.resolves`.

    Scenario: a teammate's per-commit events never landed in the shared log
    (env-propagation fragility) — the merge HEAD emitted by
    ``append_merge_commit_event`` is the ONLY surviving commit event for that
    work, and until this fix it carried no ``metadata.resolves`` at all, so
    the target concern/debt never resolved.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve()
        for args in (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "t@example.com"],
            ["config", "user.name", "Tester"],
            ["config", "commit.gpgsign", "false"],
        ):
            _git(self.repo, *args)
        (self.repo / "seed.py").write_text("x = 1\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.smm = _seed_smm(self.repo)

    def tearDown(self):
        self._tmp.cleanup()

    def _append_debt(self, content: str) -> str:
        event = _common.make_event("debt", "main", content, files=["seed.py"])
        _common.append_safe(self.smm, event)
        return event["id"]

    def _read_events(self) -> list[dict]:
        return _common.read_events_locked(self.smm, "test")

    def test_merge_event_carries_merged_in_resolves_trailer(self):
        debt_id = self._append_debt("perf: the thing is slow")

        _git(self.repo, "checkout", "-q", "-b", "story-branch")
        (self.repo / "fix.py").write_text("y = 2\n")
        _git(self.repo, "add", "-A")
        _git(
            self.repo,
            "commit",
            "-q",
            "-m",
            f"perf: make it fast\n\nResolves-Event: {debt_id}",
        )
        _git(self.repo, "checkout", "-q", "main")
        _git(
            self.repo,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "Merge story-branch",
            "story-branch",
        )

        append_merge_commit_event(str(self.repo), self.smm, "paulingalls/story-branch")

        events = self._read_events()
        commit_events = [e for e in events if e.get("type") == EVENT_TYPE_COMMIT]
        self.assertEqual(len(commit_events), 1)
        self.assertEqual(commit_events[0]["metadata"].get("resolves"), [debt_id])
        self.assertTrue(commit_events[0]["metadata"].get("has_resolves_trailer"))

        resolved = resolution.compute_resolutions(events)["resolved_debt_ids"]
        self.assertIn(debt_id, resolved, "merge backstop did not resolve the debt")

    def test_trailer_naming_absent_id_degrades_honestly(self):
        """AC3: a merged trailer naming an id absent from the live log must
        not fabricate a resolution or crash — the merge event still lands
        with the (unresolvable) id in metadata.resolves, and nothing in the
        live log is falsely marked resolved."""
        _git(self.repo, "checkout", "-q", "-b", "story-branch")
        (self.repo / "fix.py").write_text("y = 2\n")
        _git(self.repo, "add", "-A")
        _git(
            self.repo,
            "commit",
            "-q",
            "-m",
            "fix: names a ghost\n\nResolves-Event: deadbeef1234",
        )
        _git(self.repo, "checkout", "-q", "main")
        _git(
            self.repo,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "Merge story-branch",
            "story-branch",
        )

        append_merge_commit_event(str(self.repo), self.smm, "paulingalls/story-branch")

        events = self._read_events()
        commit_events = [e for e in events if e.get("type") == EVENT_TYPE_COMMIT]
        self.assertEqual(len(commit_events), 1)
        resolutions = resolution.compute_resolutions(events)
        all_resolved = (
            resolutions["resolved_debt_ids"] | resolutions["resolved_concern_ids"]
        )
        self.assertNotIn("deadbeef1234", all_resolved)

    def test_ff_merge_omits_resolves_without_crashing(self):
        """A degenerate ff-merge has no `^2` parent; merged_range_bodies must
        fail safe (empty string) rather than raise into the caller."""
        _git(self.repo, "checkout", "-q", "-b", "story-branch")
        (self.repo / "fix.py").write_text("y = 2\n")
        _git(self.repo, "add", "-A")
        _git(
            self.repo,
            "commit",
            "-q",
            "-m",
            "chore: ff only",
        )
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "-q", "--ff-only", "story-branch")

        append_merge_commit_event(str(self.repo), self.smm, "paulingalls/story-branch")

        events = self._read_events()
        commit_events = [e for e in events if e.get("type") == EVENT_TYPE_COMMIT]
        self.assertEqual(len(commit_events), 1)
        self.assertNotIn("resolves", commit_events[0]["metadata"])


if __name__ == "__main__":
    unittest.main()
