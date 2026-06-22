#!/usr/bin/env python3
"""Tests for scripts/markers.py — core marker CRUD and constants.

Review cycle, render markers, and agent cleanup in test_markers_review.py.
"""

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
            m.name = "changed"  # type: ignore[misc]  # frozen — assignment expected to raise


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
        for m in (markers.TDD_TRACKER, markers.REVIEW_CYCLE):
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
        path = self.smm_dir / ".tdd-main.json"
        path.write_text(json.dumps({"writes": [], "test_written": False}))
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "main")
        )

    def test_json_marker_invalid_json_returns_false(self):
        path = self.smm_dir / ".tdd-main.json"
        path.write_text("not json")
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "main")
        )

    def test_json_marker_non_dict_returns_false(self):
        path = self.smm_dir / ".tdd-main.json"
        path.write_text(json.dumps([1, 2, 3]))
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.TDD_TRACKER, "main")
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
        data = {"writes": [], "test_written": True}
        (self.smm_dir / ".tdd-main.json").write_text(json.dumps(data))
        self.assertEqual(
            markers.marker_read(self.smm_dir, markers.TDD_TRACKER, "main"), data
        )

    def test_read_json_corrupt_returns_none(self):
        (self.smm_dir / ".tdd-main.json").write_text("not json{")
        self.assertIsNone(
            markers.marker_read(self.smm_dir, markers.TDD_TRACKER, "main")
        )

    def test_read_json_non_dict_returns_none(self):
        (self.smm_dir / ".tdd-main.json").write_text(json.dumps("string"))
        self.assertIsNone(
            markers.marker_read(self.smm_dir, markers.TDD_TRACKER, "main")
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
        data = {"writes": ["src/foo.py"], "test_written": False}
        (self.smm_dir / ".tdd-main.json").write_text(json.dumps(data))
        result = markers.marker_consume(self.smm_dir, markers.TDD_TRACKER, "main")
        self.assertEqual(result, data)
        self.assertFalse((self.smm_dir / ".tdd-main.json").exists())

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


class TestMarkerNameConstants(unittest.TestCase):
    """Tests for marker_names.py constant values."""

    def test_needs_execution_plan_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_EXECUTION_PLAN, ".needs-execution-plan")

    def test_needs_system_context_exists(self):
        import marker_names

        self.assertEqual(marker_names.NEEDS_SYSTEM_CONTEXT, ".needs-system-context")

    def test_accept_in_flight_exists(self):
        import marker_names

        self.assertEqual(marker_names.ACCEPT_IN_FLIGHT, ".accept-in-flight")


class TestAcceptInFlightMarker(_HookTestCase):
    """The ACCEPT_IN_FLIGHT suppression marker round-trips and is swept."""

    def test_round_trip(self):
        import markers

        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))
        self.assertEqual(
            markers.marker_consume(self.smm_dir, markers.ACCEPT_IN_FLIGHT), "1"
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))

    def test_swept_as_stale_session_marker(self):
        import markers

        self.assertIn(markers.ACCEPT_IN_FLIGHT, markers._STALE_SESSION_MARKERS)
        markers.marker_write(self.smm_dir, markers.ACCEPT_IN_FLIGHT, "1")
        markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT_IN_FLIGHT))


# [story-004] Removed test_accept_active_exists + TestAcceptActiveMarker —
# the ACCEPT_ACTIVE marker name + MarkerDef are deleted; close-then-done
# replaces the marker with sprint_state.has_reviewing_stories in
# pre_tool_write (pinned in test_pre_tool_write_gates.py).


if __name__ == "__main__":
    unittest.main()
