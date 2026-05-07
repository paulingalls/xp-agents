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


class TestSelectInMotionStories(unittest.TestCase):
    """Story-002 widening contract: concern_triage and acceptance_types
    both surface info for the in-motion (in-progress + reviewing) story
    set, not just in-progress. The shared filter helper is the seam.
    """

    def test_includes_in_progress(self):
        stories = [{"id": "s1", "status": "in-progress"}]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_includes_reviewing(self):
        stories = [{"id": "s1", "status": "reviewing"}]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_includes_both_when_mixed(self):
        stories = [
            {"id": "s1", "status": "reviewing"},
            {"id": "s2", "status": "in-progress"},
            {"id": "s3", "status": "ready"},
            {"id": "s4", "status": "scheduled"},
            {"id": "s5", "status": "done"},
            {"id": "s6", "status": "deferred"},
        ]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual({s["id"] for s in result}, {"s1", "s2"})

    def test_excludes_terminal_and_queued(self):
        stories = [
            {"id": "s1", "status": "ready"},
            {"id": "s2", "status": "scheduled"},
            {"id": "s3", "status": "done"},
            {"id": "s4", "status": "deferred"},
        ]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
