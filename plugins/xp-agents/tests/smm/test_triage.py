#!/usr/bin/env python3
"""Tests for smm/triage.py — shared triage helpers.

Covers: find_unresolved, find_overlapping_commits.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import triage
from conftest import make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN, EVENT_TYPE_DEBT


class TestFindUnresolved(unittest.TestCase):
    """find_unresolved returns unresolved events of a given type, newest first."""

    def test_returns_unresolved_concerns_newest_first(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="First")
        c1["ts"] = "2026-01-01T00:00:00Z"
        c2 = make_event(EVENT_TYPE_CONCERN, content="Second")
        c2["ts"] = "2026-01-02T00:00:00Z"
        result = triage.find_unresolved([c1, c2], "concern", set())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "Second")

    def test_excludes_resolved(self):
        c1 = make_event(EVENT_TYPE_CONCERN, content="Resolved one")
        c2 = make_event(EVENT_TYPE_CONCERN, content="Still open")
        result = triage.find_unresolved([c1, c2], "concern", {c1["id"]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Still open")

    def test_filters_by_type(self):
        c = make_event(EVENT_TYPE_CONCERN, content="A concern")
        d = make_event(EVENT_TYPE_DEBT, content="Some debt")
        result = triage.find_unresolved([c, d], "concern", set())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], EVENT_TYPE_CONCERN)

    def test_empty_events(self):
        result = triage.find_unresolved([], "concern", set())
        self.assertEqual(result, [])


class TestFindOverlappingCommits(unittest.TestCase):
    """find_overlapping_commits finds commits whose files overlap a concern."""

    def test_finds_overlapping_commit(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(EVENT_TYPE_COMMIT, content="fix app", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 1)

    def test_ignores_commits_before_concern(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2099-01-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="old fix", files=["src/app.ts"])
        commit["ts"] = "2000-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_no_overlap_different_files(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        commit = make_event(
            EVENT_TYPE_COMMIT, content="fix other", files=["src/other.ts"]
        )
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_same_timestamp_excluded(self):
        """Commit at exact same timestamp as concern is excluded."""
        concern = make_event(EVENT_TYPE_CONCERN, content="Issue", files=["src/app.ts"])
        concern["ts"] = "2026-06-01T00:00:00Z"
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2026-06-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)

    def test_concern_without_files_returns_empty(self):
        concern = make_event(EVENT_TYPE_CONCERN, content="No files")
        commit = make_event(EVENT_TYPE_COMMIT, content="fix", files=["src/app.ts"])
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = triage.find_overlapping_commits(concern, [commit])
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
