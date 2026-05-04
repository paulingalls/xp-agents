#!/usr/bin/env python3
"""Tests for concern_triage.py — xp-accept concern triage preload.

Covers: find_concerns_for_stories, format output.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "skills" / "xp-accept" / "scripts"),
)

import concern_triage
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN


class TestFindConcernsForStory(unittest.TestCase):
    """find_concerns_for_story filters open concerns by story file_domain overlap."""

    def test_finds_overlapping_concern(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug in auth", files=["scripts/auth.py"]
        )
        story = {"id": "story-001", "file_domain": ["scripts/auth.py"]}
        result = concern_triage.find_concerns_for_story(story, [concern])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_excludes_non_overlapping(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug in db", files=["scripts/db.py"]
        )
        story = {"id": "story-001", "file_domain": ["scripts/auth.py"]}
        result = concern_triage.find_concerns_for_story(story, [concern])
        self.assertEqual(len(result), 0)

    def test_story_without_file_domain(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug", files=["scripts/auth.py"]
        )
        story = {"id": "story-001"}
        result = concern_triage.find_concerns_for_story(story, [concern])
        self.assertEqual(len(result), 0)

    def test_file_domain_with_em_dash_description(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug", files=["scripts/auth.py"]
        )
        story = {
            "id": "story-001",
            "file_domain": ["scripts/auth.py — authentication module"],
        }
        result = concern_triage.find_concerns_for_story(story, [concern])
        self.assertEqual(len(result), 1)


class TestFormatConcernTriage(unittest.TestCase):
    """format_concern_triage produces markdown output for preload."""

    def test_formats_concern_with_id_and_files(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug in auth", files=["scripts/auth.py"]
        )
        result = concern_triage.format_concern_triage("story-001", [concern], [])
        self.assertIn("### Concerns for story-001", result)
        self.assertIn(concern["id"], result)
        self.assertIn("scripts/auth.py", result)

    def test_empty_concerns_returns_empty(self):
        result = concern_triage.format_concern_triage("story-001", [], [])
        self.assertEqual(result, "")

    def test_likely_addressed_annotation(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug in auth", files=["scripts/auth.py"]
        )
        commit = make_event(
            EVENT_TYPE_COMMIT, content="Fix auth bug", files=["scripts/auth.py"]
        )
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = concern_triage.format_concern_triage("story-001", [concern], [commit])
        self.assertIn("LIKELY ADDRESSED", result)


if __name__ == "__main__":
    unittest.main()
