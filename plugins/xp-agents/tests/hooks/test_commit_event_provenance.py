#!/usr/bin/env python3
"""What the rebuild refuses to claim: HEAD's provenance, read from git.

Split out of `test_commit_event_rebuild.py`, which sat at exactly its own
450-line sub-cap with no headroom until a back-merge added eight lines. The
seam is not chronological: every case here drives ONE decision —
`commit_emit._freshly_landed_commit_kind`, which answers how the head in front
of it landed (a plain commit, a merge, or nothing this command can describe)
from the committer timestamp, the parent count and the reflog action.

The consumer keeps the cases about what the rebuild DOES once that answer is
"yes": the event it builds, the trailer it resolves, the trace it replaces, the
review cycle it resets. This file keeps the ones about answering at all.

Why a real repo and not patched lookups: all three discriminators are
properties of git's own history, so a stub would let us assert the answers into
existence. `_RebuildTestCase` provides the repo; see its module docstring.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _commit_repo_case import UNREADABLE_F, _RebuildTestCase


class TestAmbiguousHeadIsNotClaimed(_RebuildTestCase):
    """AC-6 and the reflog discriminators. Recording an AMBIGUOUS head would
    fabricate a commit this command never made, and honor a trailer from
    someone else's history — a worse fail-open than the one being fixed.

    A fresh two-parent merge is no longer one of the ambiguous cases: the
    reflog says how it landed, and it is recorded as a merge (see below). The
    ambiguity that still refuses is an OLD head, or a head whose reflog cannot
    be read at all."""

    def test_rejection_atop_old_unrecorded_history(self):
        """AC-6: HEAD is old, so the just-run command did not produce it."""
        self.commit("feat: yesterday's work", age_seconds=6 * 3600)
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def _merge_a_side_branch(self) -> None:
        """Leave HEAD on a fresh two-parent `--no-ff` merge commit."""
        self.commit("feat: mainline")
        base = self.git("rev-parse", "HEAD~1")
        self.git("checkout", "-q", "-b", "side", base)
        self.commit("feat: side work", path="src/side.py")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "Merge side", "side")

    def test_young_merge_head_is_recorded_as_a_merge_not_a_plain_commit(self):
        """SUPERSEDES the earlier AC-7 stance, which refused a merge HEAD
        outright. Two of its three costs are gone — the event carries
        `is_merge`, which is exactly what excludes it from the
        resolves-link-rate denominator. The third stands: `files` is the
        FIRST-PARENT diff, every file the merged branch touched (one here only
        because the side branch is one commit), which is also the file set
        `merge_commit_event` already records for close-cycle merges, where
        `is_merge` likewise keeps the breadth out of the metrics. What the
        refusal bought was a hand-run merge going unrecorded, while that
        emitter called the same hole a hole.

        The distinction the old name reached for still holds: a merge HEAD is
        not a PLAIN commit. It is now recorded AS a merge instead of refused
        for not being plain."""
        self._merge_a_side_branch()
        self.run_hook(UNREADABLE_F)
        events = self.commit_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["metadata"]["is_merge"])
        self.assertEqual(events[0]["files"], ["src/side.py"])
        # Claimed, so no head-moved trace: one observation per commit.
        self.assertEqual(self.concerns(), [])

    def test_a_fast_forward_onto_a_merge_commit_claims_nothing(self):
        """A fast-forward creates NO commit, and every other guard passes.

        The trap the merge arm walked into: `%gs` spells this `merge X:
        Fast-forward`, and the action is read as everything before the colon —
        so it has the same leading word as a real merge. Landing on a merge
        commit (2 parents, and origin tips very often are one) routes it INTO
        the merge arm rather than vetoing, and a tip pushed minutes ago is
        fresh. Recording here claims another clone's hash, message and files as
        this command's work, and honors that body's trailers against real ids.

        Reproduced on the back-merge that found it: only the 5-minute freshness
        bound stood between the flow `teammate pushes a story-close merge, lead
        merges` and a fabricated event.
        """
        self.commit("feat: mainline")
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "-b", "theirs")
        self.commit("feat: their work", path="src/theirs.py")
        self.git("checkout", "-q", "-b", "side", base)
        self.commit("feat: side work", path="src/side.py")
        self.git("checkout", "-q", "theirs")
        self.git("merge", "-q", "--no-ff", "-m", "Merge side into theirs", "side")
        their_tip = self.head()

        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "theirs")
        # State the two facts that make every other guard pass, so a later
        # reader sees this is not refused for being stale or single-parent.
        self.assertEqual(self.head(), their_tip, "setup did not fast-forward")
        self.assertEqual(len(self.git("show", "-s", "--format=%P").split()), 2)
        action = self.git("reflog", "-1", "--format=%gs")
        self.assertTrue(action.startswith("merge "), f"unexpected reflog: {action!r}")

        self.run_hook("git merge --ff-only theirs")

        self.assertEqual(self.commit_events(), [], "claimed another clone's merge")
        # The trace still fires: HEAD moved with nothing recorded, which is a
        # real observation. Refusing must not also silence it.
        self.assertEqual(len(self.concerns()), 1)

    def test_merge_head_with_no_readable_reflog_is_refused(self):
        """A merge HEAD is claimed on the reflog, so with the reflog gone it is
        refused — the plain arm's fail-closed posture on absence. It no longer
        isolates the parent count: the case above RECORDS, so that test is what
        fails if the parent-count arm is deleted (measured)."""
        self._merge_a_side_branch()
        self.erase_reflog()
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_amended_head_is_not_a_fresh_commit(self):
        """`commit (amend)` rewrites HEAD to a new hash whose predecessor
        may already carry an event. The timestamp cannot tell them apart;
        the reflog can."""
        self.commit("feat: x")
        self.git("commit", "-q", "--amend", "-m", "feat: x amended")
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_reset_to_a_young_commit_is_not_a_commit(self):
        """HEAD young, single-parent, and still not produced by committing."""
        self.commit("feat: a")
        target = self.head()
        self.commit("feat: b")
        self.git("reset", "-q", "--hard", target)
        self.run_hook(UNREADABLE_F)
        self.assertEqual(self.commit_events(), [])

    def test_readable_message_that_missed_is_evidence_against_recording(self):
        """The hole a whole-suite run found. A plain `-m 'subject'` the hook
        CAN read, which did not match HEAD, is positive evidence this command
        did not make HEAD — a rejection on top of recent history, or a
        commit-msg hook rewrite. HEAD here is fresh, single-parent and
        reflogged as `commit`, so those three guards all pass and only the
        readable-message check stands between us and fabricating an event
        (and honoring the older commit's trailer) off someone else's work."""
        self.commit("feat: history that predates this command")
        self.run_hook("git commit -m 'a subject that never landed'")
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)

    def test_missing_reflog_vetoes_the_rebuild(self):
        """`core.logAllRefUpdates` can be off (bare repos, and anyone who set
        it), and `git reflog expire` empties the log. Absence VETOES.

        Degrading to allow was the widest residual fabrication path: with no
        reflog, an amend or a reset/ff-merge onto a fresh unrecorded commit
        followed by a failed unreadable commit satisfies freshness, parent count
        and unreadability, and records an event for a commit this command did
        not make — whose trailer then resolves real ids on false evidence.

        Vetoing costs a reflog-less repo only the trace it already got before
        this story existed, so it is not a regression there. The asymmetry is
        lopsided, and it matches the recorded fail-closed doctrine for an
        unresolvable `git -C` target.

        NOT a fresh clone, which does have a reflog: `git clone` writes a
        `clone: from <url>` HEAD entry, so that case is vetoed on the action."""
        self.commit("feat: x")
        self.erase_reflog()
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 0)

    def test_future_committer_date_is_not_maximally_fresh(self):
        """A future committer timestamp must not read as fresh.

        `now - ts > MAX` alone is one-sided: a clock-skewed committing host
        yields a negative age, which compares under any positive bound and so
        defeats the freshness guard outright rather than tripping it. Bounding
        at both ends (`0 <= age <= MAX`) is how the housekeeping gate reads the
        same helper. Negative `age_seconds` forward-dates the commit."""
        self.commit("feat: x", age_seconds=-7200)
        self.run_hook(UNREADABLE_F)
        self.assertEqual(len(self.commit_events()), 0)


if __name__ == "__main__":
    unittest.main()
