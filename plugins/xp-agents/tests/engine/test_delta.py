#!/usr/bin/env python3
"""Tests for watermarks, symlink protection, read_delta, and curation watermarks.

Split from smm/test_engine.py — covers:
  TestWatermark, TestSymlinkProtection, TestReadDelta, TestCurationWatermark.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import materialize
import read_delta
from conftest import _SMMTestCase, make_event

# ===========================================================================
# Read Delta — Watermark
# ===========================================================================


class TestWatermark(_SMMTestCase):
    def test_no_watermark_returns_0(self):
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_write_and_read_watermark(self):
        read_delta.write_watermark(self.smm_dir, "main", 42)
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 42)

    def test_corrupted_watermark_returns_0(self):
        wm_file = self.smm_dir / ".watermark-main"
        wm_file.write_text("not-a-number")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_atomic_write_no_temp_files(self):
        read_delta.write_watermark(self.smm_dir, "test", 10)
        tmp_files = list(self.smm_dir.glob(".wm-test-*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_per_agent_watermarks(self):
        read_delta.write_watermark(self.smm_dir, "alice", 10)
        read_delta.write_watermark(self.smm_dir, "bob", 20)
        self.assertEqual(read_delta.read_watermark(self.smm_dir, "alice"), 10)
        self.assertEqual(read_delta.read_watermark(self.smm_dir, "bob"), 20)

    def test_reject_agent_id_with_slash(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "../escape", 10)

    def test_reject_agent_id_with_dotdot(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "..", 10)

    def test_reject_agent_id_with_null(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent\x00id", 10)

    def test_reject_empty_agent_id(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "", 10)

    def test_read_watermark_rejects_bad_agent_id(self):
        with self.assertRaises(ValueError):
            read_delta.read_watermark(self.smm_dir, "../escape")

    def test_rejects_space(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent name", 10)

    def test_rejects_semicolon(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent;cmd", 10)

    def test_rejects_backtick(self):
        with self.assertRaises(ValueError):
            read_delta.write_watermark(self.smm_dir, "agent`cmd`", 10)

    def test_accepts_colon(self):
        read_delta.write_watermark(self.smm_dir, "xp-quality:reviewer", 10)
        wm = read_delta.read_watermark(self.smm_dir, "xp-quality:reviewer")
        self.assertEqual(wm, 10)

    def test_accepts_hyphen(self):
        read_delta.write_watermark(self.smm_dir, "xp-housekeeping", 5)
        wm = read_delta.read_watermark(self.smm_dir, "xp-housekeeping")
        self.assertEqual(wm, 5)

    def test_watermark_file_permissions(self):
        read_delta.write_watermark(self.smm_dir, "main", 10)
        wm_file = self.smm_dir / ".watermark-main"
        mode = wm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"watermark mode is {oct(mode)}")


# ===========================================================================
# Symlink Protection
# ===========================================================================


class TestSymlinkProtection(_SMMTestCase):
    """Symlinks at lock/event paths must be rejected."""

    def test_read_delta_rejects_lock_symlink(self):
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock-rd")
        with self.assertRaises(OSError):
            read_delta.read_events_from(self.smm_dir, 0)

    def test_materialize_rejects_lock_symlink(self):
        self._write_events([make_event()])
        lock_file = self.smm_dir / "events.lock"
        lock_file.unlink()
        lock_file.symlink_to("/tmp/decoy-lock-mat")
        with self.assertRaises(OSError):
            materialize.parse_events(self.smm_dir)


# ===========================================================================
# Read Delta — End-to-End
# ===========================================================================


class TestReadDelta(_SMMTestCase):
    def test_no_watermark_reads_all(self):
        self._write_events([make_event(), make_event()])
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 2)

    def test_watermark_reads_new_only(self):
        self._write_events([make_event(content="old")])
        read_delta.read_delta(self.smm_dir, "main")
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "new")

    def test_watermark_advances(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main")
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 1)

    def test_watermark_beyond_file_empty_result(self):
        self._write_events([make_event()])
        read_delta.write_watermark(self.smm_dir, "main", 100)
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 0)

    def test_no_update_flag(self):
        self._write_events([make_event()])
        read_delta.read_delta(self.smm_dir, "main", update_watermark=False)
        wm = read_delta.read_watermark(self.smm_dir, "main")
        self.assertEqual(wm, 0)

    def test_missing_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        events = read_delta.read_delta(fake_dir, "main")
        self.assertEqual(len(events), 0)

    def test_empty_file(self):
        events = read_delta.read_delta(self.smm_dir, "main")
        self.assertEqual(len(events), 0)

    def test_multiple_agents_independent_watermarks(self):
        self._write_events([make_event(), make_event(), make_event()])
        read_delta.read_delta(self.smm_dir, "alice")
        # Alice at 3, bob at 0
        with open(self.events_file, "a") as f:
            f.write(json.dumps(make_event(content="new")) + "\n")
        alice_events = read_delta.read_delta(self.smm_dir, "alice")
        bob_events = read_delta.read_delta(self.smm_dir, "bob")
        self.assertEqual(len(alice_events), 1)
        self.assertEqual(len(bob_events), 4)


# ---------------------------------------------------------------------------
# Curation watermark tests (M1)
# ---------------------------------------------------------------------------


class TestCurationWatermark(_SMMTestCase):
    """Tests for curation watermark read/write."""

    def test_no_watermark_returns_defaults(self):
        """Missing .curation-watermark returns default dict."""
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["timestamp"], "")
        self.assertEqual(result["agent_id"], "")

    def test_write_and_read_roundtrip(self):
        """Write then read returns correct values."""
        materialize.write_curation_watermark(self.smm_dir, 42, "xp-housekeeping")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 42)
        self.assertEqual(result["agent_id"], "xp-housekeeping")
        # timestamp should be a non-empty ISO8601 string
        self.assertTrue(len(result["timestamp"]) > 0)

    def test_corrupted_watermark_returns_defaults(self):
        """Garbage in .curation-watermark returns defaults."""
        wm_file = self.smm_dir / ".curation-watermark"
        wm_file.write_text("not json at all {{{")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["timestamp"], "")
        self.assertEqual(result["agent_id"], "")

    def test_watermark_file_permissions(self):
        """Written watermark has mode 0o600."""
        materialize.write_curation_watermark(self.smm_dir, 10, "test")
        wm_file = self.smm_dir / ".curation-watermark"
        mode = wm_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_overwrite_reads_latest(self):
        """Second write overwrites; read returns second value."""
        materialize.write_curation_watermark(self.smm_dir, 10, "agent-a")
        materialize.write_curation_watermark(self.smm_dir, 50, "agent-b")
        result = materialize.read_curation_watermark(self.smm_dir)
        self.assertEqual(result["event_count"], 50)
        self.assertEqual(result["agent_id"], "agent-b")


if __name__ == "__main__":
    unittest.main()
