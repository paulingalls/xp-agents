#!/usr/bin/env python3
"""Tests for scripts/markers.py — marker infrastructure."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from conftest import _HookTestCase

# ---------------------------------------------------------------------------
# MarkerDef
# ---------------------------------------------------------------------------


class TestMarkerDef(unittest.TestCase):
    """Test MarkerDef dataclass behavior."""

    def test_fixed_filename(self):
        m = markers.MarkerDef(".needs-kickoff", "text")
        self.assertEqual(m.filename(), ".needs-kickoff")

    def test_agent_scoped_filename(self):
        m = markers.MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
        self.assertEqual(m.filename("main"), ".tdd-main.json")

    def test_agent_scoped_missing_agent_id_raises(self):
        m = markers.MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
        with self.assertRaises(ValueError):
            m.filename()

    def test_agent_scoped_empty_agent_id_raises(self):
        m = markers.MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
        with self.assertRaises(ValueError):
            m.filename("")

    def test_agent_scoped_invalid_agent_id_raises(self):
        m = markers.MarkerDef(".tdd-{agent_id}.json", "json", agent_scoped=True)
        with self.assertRaises(ValueError):
            m.filename("../../etc/passwd")

    def test_frozen(self):
        m = markers.MarkerDef(".test", "text")
        with self.assertRaises(AttributeError):
            m.name = "changed"


# ---------------------------------------------------------------------------
# marker_path
# ---------------------------------------------------------------------------


class TestMarkerPath(_HookTestCase):
    """Test marker_path returns correct Path."""

    def test_fixed_marker(self):
        path = markers.marker_path(self.smm_dir, markers.KICKOFF)
        self.assertEqual(path, self.smm_dir / ".needs-kickoff")

    def test_agent_scoped_marker(self):
        path = markers.marker_path(self.smm_dir, markers.TDD_TRACKER, "main")
        self.assertEqual(path, self.smm_dir / ".tdd-main.json")

    def test_all_constants_produce_valid_paths(self):
        for m in (markers.KICKOFF, markers.PLAN_AWAITING_REVIEW):
            path = markers.marker_path(self.smm_dir, m)
            self.assertTrue(path.name.startswith("."))
        for m in (markers.SECURITY_TRIAGED, markers.TDD_TRACKER, markers.REVIEW_CYCLE):
            path = markers.marker_path(self.smm_dir, m, "main")
            self.assertTrue(path.name.startswith("."))


# ---------------------------------------------------------------------------
# marker_exists
# ---------------------------------------------------------------------------


class TestMarkerExists(_HookTestCase):
    """Test marker_exists with symlink safety and content validation."""

    def test_missing_file_returns_false(self):
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.KICKOFF))

    def test_text_marker_exists(self):
        (self.smm_dir / ".needs-kickoff").write_text("startup")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.KICKOFF))

    def test_json_marker_exists_with_valid_json(self):
        path = self.smm_dir / ".security-triaged-main"
        path.write_text(json.dumps({"ts": "2026-03-26T00:00:00Z"}))
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        )

    def test_json_marker_invalid_json_returns_false(self):
        path = self.smm_dir / ".security-triaged-main"
        path.write_text("not json")
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        )

    def test_json_marker_non_dict_returns_false(self):
        path = self.smm_dir / ".security-triaged-main"
        path.write_text(json.dumps([1, 2, 3]))
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        )

    def test_symlink_returns_false(self):
        real = self.smm_dir / ".real-file"
        real.write_text("data")
        link = self.smm_dir / ".needs-kickoff"
        link.symlink_to(real)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.KICKOFF))

    def test_agent_scoped_exists(self):
        path = self.smm_dir / ".tdd-main.json"
        path.write_text(json.dumps({"writes": [], "test_written": False}))
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "main")
        )


# ---------------------------------------------------------------------------
# marker_write
# ---------------------------------------------------------------------------


class TestMarkerWrite(_HookTestCase):
    """Test marker_write for text and JSON types."""

    def test_write_text_marker(self):
        markers.marker_write(self.smm_dir, markers.KICKOFF, "startup")
        path = self.smm_dir / ".needs-kickoff"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "startup")

    def test_write_json_marker(self):
        data = {"ts": "2026-03-26T00:00:00Z"}
        markers.marker_write(self.smm_dir, markers.SECURITY_TRIAGED, data, "main")
        path = self.smm_dir / ".security-triaged-main"
        self.assertEqual(json.loads(path.read_text()), data)

    def test_write_agent_scoped_marker(self):
        data = {"writes": ["src/foo.py"], "test_written": False}
        markers.marker_write(self.smm_dir, markers.TDD_TRACKER, data, "main")
        path = self.smm_dir / ".tdd-main.json"
        self.assertEqual(json.loads(path.read_text()), data)

    def test_write_rejects_symlink(self):
        real = self.smm_dir / ".real-file"
        real.write_text("old")
        link = self.smm_dir / ".needs-kickoff"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            markers.marker_write(self.smm_dir, markers.KICKOFF, "startup")

    def test_write_overwrites_existing(self):
        markers.marker_write(self.smm_dir, markers.KICKOFF, "startup")
        markers.marker_write(self.smm_dir, markers.KICKOFF, "clear")
        self.assertEqual((self.smm_dir / ".needs-kickoff").read_text(), "clear")

    def test_write_sets_restricted_permissions(self):
        markers.marker_write(self.smm_dir, markers.KICKOFF, "startup")
        path = self.smm_dir / ".needs-kickoff"
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


# ---------------------------------------------------------------------------
# marker_read
# ---------------------------------------------------------------------------


class TestMarkerRead(_HookTestCase):
    """Test marker_read for text and JSON types."""

    def test_read_missing_returns_none(self):
        self.assertIsNone(markers.marker_read(self.smm_dir, markers.KICKOFF))

    def test_read_text_marker(self):
        (self.smm_dir / ".needs-kickoff").write_text("startup")
        self.assertEqual(markers.marker_read(self.smm_dir, markers.KICKOFF), "startup")

    def test_read_text_strips_whitespace(self):
        (self.smm_dir / ".needs-kickoff").write_text("  clear  \n")
        self.assertEqual(markers.marker_read(self.smm_dir, markers.KICKOFF), "clear")

    def test_read_json_marker(self):
        data = {"ts": "2026-03-26T00:00:00Z"}
        (self.smm_dir / ".security-triaged-main").write_text(json.dumps(data))
        self.assertEqual(
            markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main"), data
        )

    def test_read_json_corrupt_returns_none(self):
        (self.smm_dir / ".security-triaged-main").write_text("not json{")
        self.assertIsNone(
            markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        )

    def test_read_json_non_dict_returns_none(self):
        (self.smm_dir / ".security-triaged-main").write_text(json.dumps("string"))
        self.assertIsNone(
            markers.marker_read(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        )

    def test_read_symlink_returns_none(self):
        real = self.smm_dir / ".real-file"
        real.write_text("data")
        link = self.smm_dir / ".needs-kickoff"
        link.symlink_to(real)
        self.assertIsNone(markers.marker_read(self.smm_dir, markers.KICKOFF))

    def test_read_agent_scoped(self):
        data = {"writes": [], "test_written": True}
        (self.smm_dir / ".tdd-main.json").write_text(json.dumps(data))
        self.assertEqual(
            markers.marker_read(self.smm_dir, markers.TDD_TRACKER, "main"),
            data,
        )


# ---------------------------------------------------------------------------
# marker_consume
# ---------------------------------------------------------------------------


class TestMarkerConsume(_HookTestCase):
    """Test marker_consume (read + delete)."""

    def test_consume_text_marker(self):
        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = markers.marker_consume(self.smm_dir, markers.KICKOFF)
        self.assertEqual(result, "startup")
        self.assertFalse((self.smm_dir / ".needs-kickoff").exists())

    def test_consume_json_marker(self):
        data = {"ts": "2026-03-26T00:00:00Z"}
        (self.smm_dir / ".security-triaged-main").write_text(json.dumps(data))
        result = markers.marker_consume(self.smm_dir, markers.SECURITY_TRIAGED, "main")
        self.assertEqual(result, data)
        self.assertFalse((self.smm_dir / ".security-triaged-main").exists())

    def test_consume_missing_returns_none(self):
        result = markers.marker_consume(self.smm_dir, markers.KICKOFF)
        self.assertIsNone(result)

    def test_consume_symlink_returns_none(self):
        real = self.smm_dir / ".real-file"
        real.write_text("data")
        link = self.smm_dir / ".needs-kickoff"
        link.symlink_to(real)
        result = markers.marker_consume(self.smm_dir, markers.KICKOFF)
        self.assertIsNone(result)
        # Symlink should not be deleted
        self.assertTrue(link.is_symlink())


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
        # Pre-populate with some flags set
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


class TestMarkerNameConstants(unittest.TestCase):
    """Tests for marker_names.py constant values."""

    def test_needs_execution_plan_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_EXECUTION_PLAN, ".needs-execution-plan")

    def test_needs_system_context_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_SYSTEM_CONTEXT, ".needs-system-context")


if __name__ == "__main__":
    unittest.main()
