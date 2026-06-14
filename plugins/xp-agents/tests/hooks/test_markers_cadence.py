#!/usr/bin/env python3
"""Tests for markers.py — session review cadence read/write API.

Split from test_markers.py — core marker CRUD stays there, review cycle in
test_markers_review.py. story-001 foundation: the 'commit' | 'story' cadence
marker that stories 002-005 consume.
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
# Review cadence convenience functions
# ---------------------------------------------------------------------------


class TestReviewCadence(_HookTestCase):
    """Test session review cadence marker (commit | story)."""

    def test_read_default_when_missing(self):
        """No marker → 'commit' (the careful default)."""
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")

    def test_write_story_then_read(self):
        markers.write_review_cadence(self.smm_dir, "story")
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "story")

    def test_write_commit_then_read(self):
        markers.write_review_cadence(self.smm_dir, "commit")
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")

    def test_corrupt_marker_failsafes_to_commit(self):
        """An unrecognized value on disk → fail-safe to 'commit'."""
        # Bypass the validating writer to plant a garbage value.
        markers.marker_write(self.smm_dir, markers.REVIEW_CADENCE, "bogus")
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")

    def test_write_invalid_value_raises(self):
        """Writer fails loud on unknown cadence."""
        with self.assertRaises(ValueError):
            markers.write_review_cadence(self.smm_dir, "weekly")

    def test_e2e_roundtrip_each_cadence(self):
        """Round-trip every valid cadence through the public API, plus default."""
        self.assertEqual(markers.read_review_cadence(self.smm_dir), "commit")
        for cadence in markers.VALID_CADENCES:
            markers.write_review_cadence(self.smm_dir, cadence)
            self.assertEqual(markers.read_review_cadence(self.smm_dir), cadence)


if __name__ == "__main__":
    unittest.main()
