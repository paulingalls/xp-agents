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
        self.assertFalse(data["security_review_done"])

    def test_write_and_read_roundtrip(self):
        expected = {
            "last_review_commit": "abc123",
            "simplify_done": True,
            "quality_review_done": False,
            "security_review_done": False,
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
                "security_review_done": True,
            },
        )
        markers.reset_review_cycle(self.smm_dir, "main", "newcommit")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(data["last_review_commit"], "newcommit")
        self.assertFalse(data["simplify_done"])
        self.assertFalse(data["quality_review_done"])
        self.assertFalse(data["security_review_done"])

    def test_set_flag_simplify(self):
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(data["simplify_done"])

    def test_set_flag_quality_review(self):
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(data["quality_review_done"])

    def test_set_flag_security_review(self):
        markers.set_review_flag(self.smm_dir, "main", "security_review_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(data["security_review_done"])

    def test_set_flag_invalid_raises(self):
        with self.assertRaises(ValueError):
            markers.set_review_flag(self.smm_dir, "main", "bogus_flag")

    def test_set_flag_preserves_other_flags(self):
        markers.reset_review_cycle(self.smm_dir, "main", "abc")
        markers.set_review_flag(self.smm_dir, "main", "simplify_done")
        markers.set_review_flag(self.smm_dir, "main", "quality_review_done")
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertEqual(data["last_review_commit"], "abc")
        self.assertTrue(data["simplify_done"])
        self.assertTrue(data["quality_review_done"])
        self.assertFalse(data["security_review_done"])

    def test_set_flag_to_false(self):
        markers.set_review_flag(self.smm_dir, "main", "simplify_done", True)
        markers.set_review_flag(self.smm_dir, "main", "simplify_done", False)
        data = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(data["simplify_done"])


# ---------------------------------------------------------------------------
# Render markers — PENDING_RENDER_RETRO / PENDING_RENDER_SMM
# ---------------------------------------------------------------------------


class TestPendingRenderMarkers(_HookTestCase):
    """Agent-scoping and per-agent isolation for render markers."""

    def test_pending_render_retro_is_agent_scoped(self):
        self.assertTrue(markers.PENDING_RENDER_RETRO.agent_scoped)

    def test_pending_render_smm_is_agent_scoped(self):
        self.assertTrue(markers.PENDING_RENDER_SMM.agent_scoped)

    def test_pending_render_retro_filename_format(self):
        path = markers.marker_path(
            self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-a"
        )
        self.assertEqual(path.name, ".pending-render-retro-teammate-a")

    def test_pending_render_smm_filename_format(self):
        path = markers.marker_path(
            self.smm_dir, markers.PENDING_RENDER_SMM, "teammate-a"
        )
        self.assertEqual(path.name, ".pending-render-smm-teammate-a")

    def test_per_agent_isolation_retro(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, "# sig", "teammate-a"
        )
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-a"
            )
        )
        self.assertFalse(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-b"
            )
        )

    def test_per_agent_isolation_smm(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_SMM, "# sig", "teammate-a"
        )
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, "teammate-a"
            )
        )
        self.assertFalse(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_SMM, "teammate-b"
            )
        )

    def test_review_fingerprint_is_agent_scoped_json(self):
        self.assertTrue(markers.REVIEW_FINGERPRINT.agent_scoped)
        self.assertEqual(markers.REVIEW_FINGERPRINT.content_type, "json")

    def test_review_fingerprint_filename_format(self):
        path = markers.marker_path(
            self.smm_dir, markers.REVIEW_FINGERPRINT, "teammate-a"
        )
        self.assertEqual(path.name, ".review-fingerprint-teammate-a")

    def test_consume_only_removes_caller_marker(self):
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, "# sig-a", "teammate-a"
        )
        markers.marker_write(
            self.smm_dir, markers.PENDING_RENDER_RETRO, "# sig-b", "teammate-b"
        )
        result = markers.marker_consume(
            self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-a"
        )
        self.assertEqual(result, "# sig-a")
        self.assertFalse(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-a"
            )
        )
        self.assertTrue(
            markers.marker_exists(
                self.smm_dir, markers.PENDING_RENDER_RETRO, "teammate-b"
            )
        )

    def test_write_rejects_symlink_retro(self):
        real = self.smm_dir / ".real-file"
        real.write_text("old")
        link = self.smm_dir / ".pending-render-retro-teammate-a"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            markers.marker_write(
                self.smm_dir, markers.PENDING_RENDER_RETRO, "# sig", "teammate-a"
            )

    def test_write_rejects_symlink_smm(self):
        real = self.smm_dir / ".real-file"
        real.write_text("old")
        link = self.smm_dir / ".pending-render-smm-teammate-a"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            markers.marker_write(
                self.smm_dir, markers.PENDING_RENDER_SMM, "# sig", "teammate-a"
            )


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

    def test_removes_review_fingerprint(self):
        markers.marker_write(
            self.smm_dir,
            markers.REVIEW_FINGERPRINT,
            {"fingerprint": "abc123"},
            "task-1",
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.REVIEW_FINGERPRINT, "task-1")
        )
        markers.cleanup_agent_markers(self.smm_dir, "task-1")
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.REVIEW_FINGERPRINT, "task-1")
        )


if __name__ == "__main__":
    unittest.main()
