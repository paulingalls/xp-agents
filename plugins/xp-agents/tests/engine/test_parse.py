#!/usr/bin/env python3
"""Tests for parsing, index building logic.

Resolution tests in test_resolutions.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
import append_validation
import materialize
from _lock_helpers import held_events_lock
from conftest import _SMMTestCase, make_event
from event_schema import sessions_since_event

# ===========================================================================
# parse_jsonl — Shared JSONL parsing
# ===========================================================================


class TestParseJsonl(unittest.TestCase):
    """Tests for append_validation.parse_jsonl()."""

    def test_empty_string(self):
        events, skipped = append_validation.parse_jsonl("")
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_blank_lines_only(self):
        events, skipped = append_validation.parse_jsonl("\n\n  \n")
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_valid_events(self):
        raw = '{"id": "a", "type": "status"}\n{"id": "b", "type": "goal"}\n'
        events, skipped = append_validation.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["id"], "a")
        self.assertEqual(events[1]["id"], "b")
        self.assertEqual(skipped, 0)

    def test_malformed_json_skipped(self):
        raw = '{"id": "a"}\nnot-json\n{"id": "b"}\n'
        events, skipped = append_validation.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)

    def test_non_dict_skipped(self):
        raw = '{"id": "a"}\n[1, 2, 3]\n"just a string"\n{"id": "b"}\n'
        events, skipped = append_validation.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 2)

    def test_mixed_valid_and_invalid(self):
        raw = '{"ok": true}\n\nbad\n{"ok": false}\n'
        events, skipped = append_validation.parse_jsonl(raw)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)


# ===========================================================================
# Materialize — Parsing
# ===========================================================================


class TestParseEvents(_SMMTestCase):
    def test_empty_file(self):
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_missing_events_file(self):
        self.events_file.unlink()
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(events, [])
        self.assertEqual(skipped, 0)

    def test_raises_on_lock_timeout(self):
        """parse_events should raise LockTimeoutError, not silently degrade."""
        self._write_events([make_event()])
        with (
            held_events_lock(self.smm_dir),
            self.assertRaises(_append_impl.LockTimeoutError),
        ):
            materialize.parse_events(self.smm_dir)

    def test_single_event(self):
        self._write_events([make_event()])
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 0)

    def test_malformed_lines_skipped(self):
        self._write_raw_lines(
            [
                json.dumps(make_event()),
                "not json at all",
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 2)
        self.assertEqual(skipped, 1)

    def test_all_malformed(self):
        self._write_raw_lines(["bad1", "bad2", "bad3"])
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 0)
        self.assertEqual(skipped, 3)

    def test_missing_id_or_type_skipped(self):
        self._write_raw_lines(
            [
                json.dumps({"content": "no id or type"}),
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 1)

    def test_non_object_json_skipped(self):
        self._write_raw_lines(
            [
                "[1, 2, 3]",
                json.dumps(make_event()),
            ]
        )
        events, skipped = materialize.parse_events(self.smm_dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(skipped, 1)


# ===========================================================================
# sessions_since_event — Session aging utility
# ===========================================================================


class TestSessionsSinceEvent(unittest.TestCase):
    """Tests for the shared sessions_since_event utility."""

    def test_no_sessions(self):
        """Zero session_end timestamps → 0 sessions since any event."""

        self.assertEqual(sessions_since_event([], "2026-03-01T00:00:00+00:00"), 0)

    def test_event_before_all_sessions(self):
        """Event predates all session_ends → count equals number of sessions."""

        se_timestamps = [
            "2026-03-02T00:00:00+00:00",
            "2026-03-03T00:00:00+00:00",
            "2026-03-04T00:00:00+00:00",
        ]
        result = sessions_since_event(se_timestamps, "2026-03-01T00:00:00+00:00")
        self.assertEqual(result, 3)

    def test_event_after_all_sessions(self):
        """Event is newer than all session_ends → 0."""

        se_timestamps = [
            "2026-03-02T00:00:00+00:00",
            "2026-03-03T00:00:00+00:00",
        ]
        result = sessions_since_event(se_timestamps, "2026-03-05T00:00:00+00:00")
        self.assertEqual(result, 0)

    def test_event_between_sessions(self):
        """Event falls between session_ends → only counts sessions after it."""

        se_timestamps = [
            "2026-03-01T00:00:00+00:00",
            "2026-03-03T00:00:00+00:00",
            "2026-03-05T00:00:00+00:00",
        ]
        # Event at 03-02 is after first session_end but before second
        result = sessions_since_event(se_timestamps, "2026-03-02T00:00:00+00:00")
        self.assertEqual(result, 2)

    def test_event_at_exact_session_end(self):
        """Event timestamp equals a session_end → that session not counted."""

        se_timestamps = [
            "2026-03-01T00:00:00+00:00",
            "2026-03-03T00:00:00+00:00",
            "2026-03-05T00:00:00+00:00",
        ]
        # bisect_right puts equal values to the left → session at 03-03 not counted
        result = sessions_since_event(se_timestamps, "2026-03-03T00:00:00+00:00")
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
