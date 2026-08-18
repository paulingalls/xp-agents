#!/usr/bin/env python3
"""What a commit the observer records does to the review cycle — and what a
commit it FAILED to record must not do.

Split from `test_commit_observer.py` when that file reached its recorded
sub-cap. Cohesive rather than arbitrary: every row here is about the three
review records (flags, watermark, coverage) that `end_review_cycle` moves
together, and the two ways the observer can be wrong about them — resetting for
the wrong commit in the range, or resetting for one the event log never took.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _append_impl
import review_records
from _observer_case import ORDINARY_BASH, _ObserverCase


class TestReviewCycle(_ObserverCase):
    """A commit event recorded without a cycle reset leaves the previous
    cycle's quality-review flag latched, so the NEXT commit's gate reads
    satisfied off a review that predates this commit. Same hazard, and same
    fix, as `rebuild_at_head` documents."""

    def test_the_reset_is_keyed_to_the_newest_commit_recorded(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: one", path="src/a.py")
        newest = self.commit("feat: two", path="src/b.py")
        self.observe()
        flags = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(flags["quality_review_done"])
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), newest
        )

    def test_a_commit_recorded_ahead_of_this_one_keeps_the_watermark_there(self):
        """The backgrounded case, one commit later. A foreground commit that
        ALREADY reset the cycle sits at the top of the same range, so keying the
        reset to what this observer happened to record walks the watermark back
        to the older hash and clears the review that ran in between."""
        self.seed_observer()
        older = self.commit("feat: backgrounded", path="src/a.py")
        newest = self.commit("feat: foreground", path="src/b.py")
        # What `_handle_commit` already did for the foreground commit.
        self.record_commit_event(newest)
        review_records.write_review_watermark(self.smm_dir, "main", newest)
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self.observe()

        self.assertIn(older, self.recorded_hashes())
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), newest
        )
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_recording_nothing_leaves_the_cycle_alone(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.observe()
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_a_leaked_xp_agent_type_records_but_does_not_reset(self):
        """Mirrors both other commit paths: the commit event always lands, and
        only the state mutations are gated on the identity being wrong."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")
        self.commit("feat: x")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")
        self.assertEqual(len(self.commit_events()), 1)
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


class TestADroppedAppendIsNotSuccess(_ObserverCase):
    """The event log's own lock can refuse the append. `bulk_append_safe` logs
    that and returns, so "recorded" and "dropped" look identical to a caller
    reading its return — and a dropped one that advanced the marker is a commit
    no event will ever carry, which is the silence this module exists to end."""

    def test_a_dropped_event_leaves_the_range_open(self):
        self.seed_observer()
        before = self.marker()
        landed = self.commit("feat: x")
        with patch(
            "_append_impl.bulk_append",
            side_effect=_append_impl.LockTimeoutError("events.jsonl busy"),
        ):
            self.observe()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.marker(), before)
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_a_dropped_event_does_not_end_the_review_cycle(self):
        """The reset belongs to a commit the log carries. Ending the cycle for
        one that was dropped points the gate's `{sha}..HEAD` diff at a commit
        with no event and spends the coverage a review earned."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: x")
        with patch(
            "_append_impl.bulk_append",
            side_effect=_append_impl.LockTimeoutError("events.jsonl busy"),
        ):
            self.observe()
        self.assertEqual(review_records.read_review_watermark(self.smm_dir, "main"), "")
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


if __name__ == "__main__":
    unittest.main()
