#!/usr/bin/env python3
"""Tests for the MAYBE ADDRESSED formatter in commits_issues.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT


class TestFormatMaybeAddressedLine(unittest.TestCase):
    """Test the single owner of the MAYBE ADDRESSED annotation line."""

    def test_one_hit(self):
        hits = [make_event(EVENT_TYPE_COMMIT, content="Fix auth bug")]
        result = commits.format_maybe_addressed_line(hits)
        self.assertEqual(result, "  **MAYBE ADDRESSED** by: Fix auth bug")

    def test_three_hits(self):
        hits = [
            make_event(EVENT_TYPE_COMMIT, content="First fix"),
            make_event(EVENT_TYPE_COMMIT, content="Second fix"),
            make_event(EVENT_TYPE_COMMIT, content="Third fix"),
        ]
        result = commits.format_maybe_addressed_line(hits)
        self.assertEqual(
            result, "  **MAYBE ADDRESSED** by: First fix; Second fix; Third fix"
        )

    def test_five_hits_uses_first_three(self):
        hits = [
            make_event(EVENT_TYPE_COMMIT, content="1"),
            make_event(EVENT_TYPE_COMMIT, content="2"),
            make_event(EVENT_TYPE_COMMIT, content="3"),
            make_event(EVENT_TYPE_COMMIT, content="4"),
            make_event(EVENT_TYPE_COMMIT, content="5"),
        ]
        result = commits.format_maybe_addressed_line(hits)
        self.assertEqual(result, "  **MAYBE ADDRESSED** by: 1; 2; 3")

    def test_truncates_long_messages(self):
        long_msg = "x" * 100
        hits = [make_event(EVENT_TYPE_COMMIT, content=long_msg)]
        result = commits.format_maybe_addressed_line(hits)
        expected = f"  **MAYBE ADDRESSED** by: {'x' * 80}"
        self.assertEqual(result, expected)

    def test_mixed_length_messages(self):
        hits = [
            make_event(EVENT_TYPE_COMMIT, content="Short"),
            make_event(EVENT_TYPE_COMMIT, content="x" * 90),
            make_event(EVENT_TYPE_COMMIT, content="Medium length"),
        ]
        result = commits.format_maybe_addressed_line(hits)
        expected = f"  **MAYBE ADDRESSED** by: Short; {'x' * 80}; Medium length"
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
