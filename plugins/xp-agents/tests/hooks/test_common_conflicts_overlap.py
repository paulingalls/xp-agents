#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 1: overlapping working_on.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: assumption (2), convention (3), stale_question (4),
superseded (5) each live in their own test_common_conflicts_<pattern>.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import concerns
from conftest import _HookTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing a
# make_event(...) call's behavior.
from event_schema import (
    EVENT_TYPE_STATUS,
)


class TestDetectConflictsCommon(_HookTestCase):
    def test_overlapping_working_on(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        self.assertTrue(any("overlap" in c["content"].lower() for c in found))

    def test_overlap_concern_has_files_field(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap = [c for c in found if "overlap" in c["content"].lower()]
        self.assertTrue(len(overlap) > 0)
        self.assertIn("files", overlap[0])
        self.assertEqual(len(overlap[0]["files"]), 1)
        self.assertTrue(overlap[0]["files"][0].endswith("app.ts"))

    def test_no_overlap_different_file(self):
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/other.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_empty_working_on_clears_overlap(self):
        """working_on=[] should clear agent's file list."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
            make_event(EVENT_TYPE_STATUS, agent_id="other", working_on=[]),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_without_file_path_skips_pattern_1(self):
        """When file_path=None, skip overlapping working_on check."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(events, "main")
        overlap_concerns = [c for c in found if "overlap" in c["content"].lower()]
        self.assertEqual(len(overlap_concerns), 0)

    def test_overlapping_working_on_concern_has_no_references(self):
        """Pattern 1 references an agent_id, not an event id — no refs attached."""
        events = [
            make_event(
                EVENT_TYPE_STATUS, agent_id="other", working_on=["/tmp/src/app.ts"]
            ),
        ]
        found = concerns.detect_conflicts(
            events, "main", file_path="/tmp/src/app.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "overlap" in c["content"].lower())
        self.assertFalse(flag.get("references"))


if __name__ == "__main__":
    unittest.main()
