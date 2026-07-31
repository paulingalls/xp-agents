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

    def test_maybe_addressed_annotation(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="Bug in auth", files=["scripts/auth.py"]
        )
        commit = make_event(
            EVENT_TYPE_COMMIT, content="Fix auth bug", files=["scripts/auth.py"]
        )
        commit["ts"] = "2099-01-01T00:00:00Z"
        result = concern_triage.format_concern_triage("story-001", [concern], [commit])
        self.assertIn("MAYBE ADDRESSED", result)


class TestSelectInMotionStories(unittest.TestCase):
    """Story-002 widening contract (extended in sprint-069 to include
    `closing`): concern_triage and acceptance_types both surface info
    for the in-motion (in-progress + reviewing + closing) story set,
    not just in-progress. The shared filter helper is the seam.
    """

    def test_includes_in_progress(self):
        stories = [{"id": "s1", "status": "in-progress"}]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_includes_reviewing(self):
        stories = [{"id": "s1", "status": "reviewing"}]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_includes_closing(self):
        stories = [{"id": "s1", "status": "closing"}]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual([s["id"] for s in result], ["s1"])

    def test_includes_all_three_when_mixed(self):
        stories = [
            {"id": "s1", "status": "reviewing"},
            {"id": "s2", "status": "in-progress"},
            {"id": "s3", "status": "ready"},
            {"id": "s4", "status": "scheduled"},
            {"id": "s5", "status": "done"},
            {"id": "s6", "status": "deferred"},
            {"id": "s7", "status": "closing"},
        ]
        result = concern_triage.select_in_motion_stories(stories)
        self.assertEqual({s["id"] for s in result}, {"s1", "s2", "s7"})

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


class TestConcernTriageIsBounded(unittest.TestCase):
    """xp-accept's concern block had neither a per-item cap nor a count cap.

    It emits full concern bodies for every concern overlapping an in-motion
    story's file_domain, so a story touching a busy path pays the whole
    backlog. Measured 40,481 chars against a shape budget of 100 on a
    populated SMM. Same honesty contract as the triage block: an item that
    vanished reads as fixed, so the tail collapses to a counted line naming a
    runnable command rather than being dropped.
    """

    def _concerns(self, count: int) -> list[dict]:
        return [
            make_event(EVENT_TYPE_CONCERN, content="c" * 500, files=["scripts/a.py"])
            for _ in range(count)
        ]

    def test_body_is_truncated(self):
        out = concern_triage.format_concern_triage("story-001", self._concerns(1), [])
        self.assertNotIn("c" * 500, out)
        self.assertIn("c" * 100, out)

    def test_total_does_not_grow_with_concern_count(self):
        small = concern_triage.format_concern_triage(
            "story-001", self._concerns(50), []
        )
        large = concern_triage.format_concern_triage(
            "story-001", self._concerns(200), []
        )
        self.assertLessEqual(
            len(large) - len(small),
            200,
            f"grew {len(large) - len(small)} chars for 150 more concerns "
            f"({len(small)} -> {len(large)}); the tail is not collapsing",
        )

    def test_omitted_concerns_are_counted_and_named(self):
        out = concern_triage.format_concern_triage("story-001", self._concerns(200), [])
        shown = len([ln for ln in out.split("\n") if ln.startswith("- [id: ")])
        self.assertIn(f"{200 - shown} further", out)
        self.assertIn("concern_triage.py", out)

    def test_the_retrieval_path_is_runnable(self):
        parser = concern_triage._build_parser()
        args = parser.parse_args(
            ["--smm-dir", "/tmp", "--sprint-file", "/tmp/s.json", "--all"]
        )
        self.assertTrue(args.all)

    def test_all_renders_every_concern(self):
        concerns = self._concerns(200)
        capped = concern_triage.format_concern_triage("story-001", concerns, [])
        full = concern_triage.format_concern_triage(
            "story-001", concerns, [], uncapped=True
        )
        self.assertGreater(len(full), len(capped))

    def test_a_high_severity_concern_survives_the_cap(self):
        """The count cap ranks newest-first, and severity outranks recency.

        Dropping a high-severity concern behind a command while ten newer
        low-severity ones render in full is the opposite of triage.
        """
        concerns = self._concerns(50)
        concerns[-1]["severity"] = "high"
        out = concern_triage.format_concern_triage("story-001", concerns, [])
        self.assertIn(concerns[-1]["id"], out)

    def test_the_file_list_is_bounded(self):
        """The one term the count cap does not bound.

        `files` renders in full for every shown concern, so a concern naming
        200 paths costs more than the 400-char content excerpt it sits under
        — the largest on the live log names 28. Same contract as everywhere
        else here: the remainder is COUNTED, never silently dropped.
        """
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="x",
            files=[f"plugins/xp-agents/scripts/module_{i}.py" for i in range(200)],
        )
        out = concern_triage.format_concern_triage("story-001", [concern], [])
        self.assertLess(len(out), 1000)
        self.assertIn("more", out)
