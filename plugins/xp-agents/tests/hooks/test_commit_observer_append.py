#!/usr/bin/env python3
"""What the observer does when the APPEND fails, rather than the git read.

Split from `test_commit_observer_cycle.py` when the rebase row took that file
over its 450 sub-cap. The seam is the failure being pinned: the classes left
there are about the review-cycle reset an observation can OWE, while these two
are about the write itself refusing — a lock nobody released, and an SMM that
will not take the bytes.

Both matter for the same reason: `bash_post_tool` calls `observe` unguarded, so
a failure that escapes takes test detection, both commit nudges and the TDD
signals down with it for the rest of the session, and a failure that is
swallowed advances the marker past a commit no event will ever carry.
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
from commit_observer_state import OWED_RESET_FIELD


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


class TestADiskFailureDoesNotKillTheWholeHook(_ObserverCase):
    """`bulk_append` opens two files, so OSError is as real a failure as the two
    it documents — a read-only or full SMM, or a lock path someone symlinked.

    `bash_post_tool` calls `observe` unguarded, so an OSError escaping it takes
    the WHOLE PostToolUse handler: test-run detection, both commit nudges and
    the TDD signals, on every ordinary Bash for as long as the fault lasts. And
    since nothing was appended, the marker never advances and the next Bash
    walks the same range into the same raise. `write_record` in the sibling
    module already suppresses `(OSError, ValueError)`, so the shape was known.
    """

    def test_a_refused_append_leaves_the_range_open_without_raising(self):
        self.seed_observer()
        before = self.marker()
        landed = self.commit("feat: x")

        with patch("_append_impl.bulk_append", side_effect=OSError("read-only SMM")):
            self.observe()

        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.marker(), before)
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_an_unopenable_observer_lock_leaves_the_reset_owed(self):
        """The same class one call later: settling an owed reset takes the
        observer's own lock, and that open can fail for the same reasons. It
        sits OUTSIDE the reconcile's try, so it had its own route out of the
        handler — and the reset must stay owed rather than be lost to it."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: recorded under a leak", path="src/a.py")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")
        owed = (self.marker() or {}).get(OWED_RESET_FIELD)
        self.assertTrue(owed, "the leak has to leave a reset owed for this to test it")

        with patch(
            "commit_observer_state.observer_lock", side_effect=OSError("symlinked lock")
        ):
            self.observe()

        self.assertEqual((self.marker() or {}).get(OWED_RESET_FIELD), owed)
        self.observe()
        self.assertFalse(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


if __name__ == "__main__":
    unittest.main()
