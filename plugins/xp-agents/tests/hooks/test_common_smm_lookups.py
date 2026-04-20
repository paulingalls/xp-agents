#!/usr/bin/env python3
"""Tests for SMM lookup operations: debt/concern file matching.

Split from test_common_smm.py. Watermark tests live in engine/test_delta.py.
extract_file_path tests live in test_pre_tool_write.py::TestGetTargetFile.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import concerns
from conftest import make_event


class TestFindDebtForFile(unittest.TestCase):
    """Tests for concerns.find_issues_for_file()."""

    def test_matching_file(self):
        events = [
            make_event("debt", content="Legacy code", files=["/tmp/src/app.ts"]),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Legacy code")

    def test_no_match(self):
        events = [
            make_event("debt", content="Legacy code", files=["/tmp/src/other.ts"]),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_multiple_debts(self):
        events = [
            make_event("debt", content="Debt 1", files=["/tmp/src/app.ts"]),
            make_event("debt", content="Debt 2", files=["/tmp/src/app.ts"]),
            make_event("debt", content="Debt 3", files=["/tmp/src/other.ts"]),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 2)

    def test_path_normalization(self):
        """Relative path in debt event matches absolute target."""
        events = [
            make_event("debt", content="Debt", files=["src/app.ts"]),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 1)

    def test_empty_events(self):
        result = concerns.find_issues_for_file([], "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_non_debt_non_concern_events_ignored(self):
        events = [
            make_event("status", content="Working"),
            make_event("goal", content="Build app"),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_concern_without_files_ignored(self):
        events = [
            make_event("concern", content="Concern about app.ts"),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_concern_with_files_matched(self):
        events = [
            make_event(
                "concern",
                content="Marker written in worktrees",
                files=["/tmp/src/app.ts"],
            ),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Marker written in worktrees")

    def test_concern_with_files_no_match(self):
        events = [
            make_event(
                "concern",
                content="Marker issue",
                files=["/tmp/src/other.ts"],
            ),
        ]
        result = concerns.find_issues_for_file(events, "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
