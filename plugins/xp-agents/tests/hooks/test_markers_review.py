#!/usr/bin/env python3
"""Tests for markers.py — review cycle, render markers, agent cleanup.

Split from test_markers.py — core marker CRUD stays there.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _HookTestCase

# ---------------------------------------------------------------------------
# Review cycle convenience functions
# ---------------------------------------------------------------------------


class TestReviewCycle(_HookTestCase):
    """Test review cycle marker convenience functions."""

    def test_read_default_when_missing(self):
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(data["last_review_commit"], "")
        self.assertFalse(data["simplify_done"])
        self.assertFalse(data["quality_review_done"])

    def test_write_and_read_roundtrip(self):
        expected = {
            "last_review_commit": "abc123",
            "simplify_done": True,
            "quality_review_done": False,
        }
        markers.write_review_cycle(self.smm_dir, "main", expected)
        result = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(result, expected)

    def test_reset_sets_commit_and_clears_flags(self):
        markers.write_review_cycle(
            self.smm_dir,
            "main",
            {
                "last_review_commit": "old",
                "simplify_done": True,
                "quality_review_done": True,
            },
        )
        markers.reset_review_cycle(self.smm_dir, "main", "newcommit")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(data["last_review_commit"], "newcommit")
        self.assertFalse(data["simplify_done"])
        self.assertFalse(data["quality_review_done"])

    def test_set_flag_simplify(self):
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(data["simplify_done"])

    def test_set_flag_quality_review(self):
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(data["quality_review_done"])

    def test_set_flag_invalid_raises(self):
        with self.assertRaises(ValueError):
            markers.set_review_flag(self.smm_dir, "main", "bogus_flag")
        # M-4: security_review_done is no longer a valid flag.
        with self.assertRaises(ValueError):
            markers.set_review_flag(self.smm_dir, "main", "security_review_done")

    def test_set_flag_preserves_other_flags(self):
        markers.reset_review_cycle(self.smm_dir, "main", "abc")
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(data["last_review_commit"], "abc")
        self.assertTrue(data["simplify_done"])
        self.assertTrue(data["quality_review_done"])

    def test_set_flag_to_false(self):
        markers.set_review_flag(self.smm_dir, "main", "simplify_done", True)
        markers.set_review_flag(self.smm_dir, "main", "simplify_done", False)
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(data["simplify_done"])

    def test_security_review_done_no_longer_in_review_flags(self):
        """M-4: security_review_done is gone from defaults and valid flags."""
        self.assertNotIn("security_review_done", markers._REVIEW_FLAGS)
        self.assertNotIn("security_review_done", markers._DEFAULT_REVIEW_CYCLE)


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
