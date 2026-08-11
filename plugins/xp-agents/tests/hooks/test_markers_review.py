#!/usr/bin/env python3
"""Tests for markers.py — review cycle, render markers, agent cleanup.

Split from test_markers.py — core marker CRUD stays there.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import review_records
from conftest import _HookTestCase

# ---------------------------------------------------------------------------
# Review cycle convenience functions
# ---------------------------------------------------------------------------


class TestReviewCycle(_HookTestCase):
    """Test review cycle marker convenience functions."""

    def test_read_default_when_missing(self):
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(data["simplify_done"])
        self.assertFalse(data["quality_review_done"])

    def test_write_and_read_roundtrip(self):
        expected = {"simplify_done": True, "quality_review_done": False}
        review_records.write_review_flags(self.smm_dir, "main", expected)
        result = review_records.read_review_flags(self.smm_dir, "main")
        self.assertEqual(result, expected)

    def test_clear_returns_every_flag_to_false(self):
        review_records.write_review_flags(
            self.smm_dir,
            "main",
            {"simplify_done": True, "quality_review_done": True},
        )
        review_records.clear_review_flags(self.smm_dir, "main")
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(data["simplify_done"])
        self.assertFalse(data["quality_review_done"])

    def test_a_pre_split_record_reads_as_flags_only(self):
        """The record on disk at upgrade still carries the watermark field.
        It must not reappear as a flag, and the flags in it must survive —
        losing those is the block this split exists to remove."""
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_CYCLE,
            {"last_review_commit": "old", "quality_review_done": True},
            "main",
        )
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(data["quality_review_done"])
        self.assertFalse(data["simplify_done"])

    def test_set_flag_simplify(self):
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(data["simplify_done"])

    def test_set_flag_quality_review(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(data["quality_review_done"])

    def test_set_flag_invalid_raises(self):
        with self.assertRaises(ValueError):
            review_records.set_review_flag(self.smm_dir, "main", "bogus_flag")
        # M-4: security_review_done is no longer a valid flag.
        with self.assertRaises(ValueError):
            review_records.set_review_flag(self.smm_dir, "main", "security_review_done")

    def test_set_flag_preserves_other_flags(self):
        review_records.clear_review_flags(self.smm_dir, "main")
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(data["simplify_done"])
        self.assertTrue(data["quality_review_done"])

    def test_set_flag_to_false(self):
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done", True)
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done", False)
        data = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(data["simplify_done"])

    def test_security_review_done_no_longer_in_review_flags(self):
        """M-4: security_review_done is gone from defaults and valid flags."""
        self.assertNotIn("security_review_done", review_records._REVIEW_FLAGS)
        self.assertNotIn("security_review_done", review_records._DEFAULT_REVIEW_FLAGS)


class TestReviewWatermark(_HookTestCase):
    """The watermark is its own record, keyed on the repo, holding a sha."""

    def test_read_default_when_missing(self):
        self.assertEqual(review_records.read_review_watermark(self.smm_dir, "main"), "")

    def test_write_and_read_roundtrip(self):
        review_records.write_review_watermark(self.smm_dir, "main", "abc123")
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "abc123"
        )

    def test_it_is_keyed_per_repo(self):
        review_records.write_review_watermark(self.smm_dir, "main", "lead-sha")
        review_records.write_review_watermark(
            self.smm_dir, "worktree-story-001", "wt-sha"
        )
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "lead-sha"
        )

    def test_clearing_the_flags_leaves_the_watermark_alone(self):
        """Two records, two lifetimes — a review ending is not a commit."""
        review_records.write_review_watermark(self.smm_dir, "main", "abc123")
        review_records.clear_review_flags(self.smm_dir, "main")
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "abc123"
        )


class TestEndingTheCycleAtACommit(_HookTestCase):
    """One commit, two files — so a failure between them has a direction.

    The pair used to be a single atomic marker write. Two files cannot be
    written atomically, so the only thing left to choose is the ORDER, and the
    two partial states are not equally bad: flags-cleared + stale watermark
    arms the gate and over-counts (one extra review), while advanced-watermark
    + stale `quality_review_done` disarms it entirely. Both callers reach the
    partial state — merge_commit_event catches and deliberately continues.
    """

    def test_it_advances_the_watermark_and_clears_the_flags(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        review_records.end_review_cycle(self.smm_dir, "main", "main", "landed-sha")

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "landed-sha"
        )
        self.assertFalse(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_a_failure_partway_leaves_the_gate_armed_not_disarmed(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        review_records.write_review_watermark(self.smm_dir, "main", "old-sha")

        with (
            patch.object(
                review_records,
                "write_review_watermark",
                side_effect=OSError("read-only"),
            ),
            self.assertRaises(OSError),
        ):
            review_records.end_review_cycle(self.smm_dir, "main", "main", "landed-sha")

        self.assertFalse(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ],
            "the flags must already be cleared when the watermark write fails",
        )
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), "old-sha"
        )


class TestReviewMidCycle(_HookTestCase):
    """Direct truth-table coverage for the shared mid-cycle predicate —
    the single source of truth both Stop gates route through."""

    def test_no_flags_not_mid_cycle(self):
        """Missing marker (defaults) is not mid-cycle."""
        self.assertFalse(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_simplify_only_is_mid_cycle(self):
        """simplify_done set, quality_review_done not yet — review in flight."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        self.assertTrue(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_both_flags_not_mid_cycle(self):
        """Both set — completed full cycle, not mid-flight."""
        review_records.set_review_flag(self.smm_dir, "main", "simplify_done")
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.assertFalse(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_quality_only_not_mid_cycle(self):
        """Load-bearing invariant: quality_review_done WITHOUT simplify_done is
        a completed standalone self-find review, NOT mid-cycle (the old
        `any and not all` heuristic wrongly treated this as in-flight)."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.assertFalse(review_records.review_mid_cycle(self.smm_dir, "main"))


# ---------------------------------------------------------------------------
# cleanup_agent_markers
# ---------------------------------------------------------------------------


class TestCleanupAgentMarkers(_HookTestCase):
    """Test cleanup_agent_markers removes agent-scoped markers."""

    def test_removes_tdd_and_review_cycle(self):
        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, "task-1")
        markers.marker_write(
            self.smm_dir, markers.REVIEW_CYCLE, {"last_review_commit": ""}, "task-1"
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "task-1")
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.REVIEW_CYCLE, "task-1")
        )

        markers.cleanup_agent_markers(self.smm_dir, "task-1")

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "task-1")
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.REVIEW_CYCLE, "task-1")
        )

    def test_does_not_affect_other_agents(self):
        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, "task-1")
        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, {"files": []}, "task-2")
        markers.cleanup_agent_markers(self.smm_dir, "task-1")

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "task-1")
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "task-2")
        )

    def test_no_error_when_markers_missing(self):
        markers.cleanup_agent_markers(self.smm_dir, "nonexistent")


if __name__ == "__main__":
    unittest.main()
