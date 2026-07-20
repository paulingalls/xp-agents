#!/usr/bin/env python3
"""Tests for concerns.detect_conflicts — pattern 4: stale question.

Split from test_common_conflicts.py (pure move, no test-body edits).
Sibling patterns: overlap (1), assumption (2), convention (3),
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
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_QUESTION,
)


class TestDetectConflictsCommon(_HookTestCase):
    def test_stale_question_detected(self):
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        self.assertTrue(any("stale" in c["content"].lower() for c in found))

    def test_stale_question_concern_references_question(self):
        """Flag concern references the stale question id (WEAK link)."""
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        found = concerns.detect_conflicts(
            [q, *filler], "main", file_path="/tmp/x.ts", cwd="/tmp"
        )
        flag = next(c for c in found if "stale" in c["content"].lower())
        self.assertEqual(flag.get("references"), [q["id"]])

    def test_no_duplicate_stale_question(self):
        """No duplicate concern for same stale question."""
        q = make_event(EVENT_TYPE_QUESTION, priority="\U0001f534", content="Blocking?")
        filler = [make_event(content=f"filler {i}") for i in range(21)]
        existing_concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Stale question: blocking question "
            f"(id {q['id']}) has not been answered.",
        )
        events = [q, *filler, existing_concern]
        found = concerns.detect_conflicts(events, "main")
        stale_concerns = [c for c in found if "stale" in c["content"].lower()]
        self.assertEqual(len(stale_concerns), 0)


if __name__ == "__main__":
    unittest.main()
