#!/usr/bin/env python3
"""Tests for acceptance_types.py — xp-accept preload acceptance type surfacing."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "skills" / "xp-accept" / "scripts"),
)

import acceptance_types
from conftest import make_story_dict as _make_story


class TestAcceptanceTypes(unittest.TestCase):
    """format_acceptance_types outputs type per in-progress story."""

    def test_story_with_acceptance_execution(self):
        story = _make_story(
            id="story-001",
            status="in-progress",
            acceptance_execution={"type": "pytest", "command": "pytest tests/"},
        )
        sprint = {"stories": [story]}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("story-001: pytest", output)

    def test_story_without_acceptance_execution(self):
        story = _make_story(id="story-001", status="in-progress")
        sprint = {"stories": [story]}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("story-001: manual", output)

    def test_only_in_progress_stories(self):
        stories = [
            _make_story(
                id="story-001",
                status="in-progress",
                acceptance_execution={"type": "bash", "command": "bash test.sh"},
            ),
            _make_story(id="story-002", status="ready"),
            _make_story(id="story-003", status="done"),
        ]
        sprint = {"stories": stories}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("story-001: bash", output)
        self.assertNotIn("story-002", output)
        self.assertNotIn("story-003", output)

    def test_header_present(self):
        story = _make_story(id="story-001", status="in-progress")
        sprint = {"stories": [story]}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("### Acceptance Types", output)

    def test_no_in_progress_returns_empty(self):
        story = _make_story(id="story-001", status="ready")
        sprint = {"stories": [story]}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertEqual(output, "")

    def test_reviewing_story_surfaced(self):
        # Story-002: reviewing stories (teammate self-promote path) MUST
        # surface alongside in-progress so xp-accept's iteration loop sees
        # the same acceptance type info regardless of which path is active.
        story = _make_story(
            id="story-001",
            status="reviewing",
            acceptance_execution={"type": "pytest", "command": "pytest tests/"},
        )
        sprint = {"stories": [story]}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("story-001: pytest", output)

    def test_mixed_in_progress_and_reviewing_both_surfaced(self):
        # Both states appear together when teammate-A has self-promoted
        # while teammate-B is still working — orchestrator iterates the
        # full set as picked by preload's reviewing-first dispatch.
        stories = [
            _make_story(
                id="story-001",
                status="reviewing",
                acceptance_execution={"type": "pytest", "command": "pytest"},
            ),
            _make_story(
                id="story-002",
                status="in-progress",
                acceptance_execution={"type": "bash", "command": "bash t.sh"},
            ),
        ]
        sprint = {"stories": stories}
        output = acceptance_types.format_acceptance_types(sprint)
        self.assertIn("story-001: pytest", output)
        self.assertIn("story-002: bash", output)

    def test_manual_block_with_command_shows_automated_routing(self):
        # story-021/023: Step 1 routes on command PRESENCE, not type — a
        # manual-typed block carrying a command runs the automated path, so
        # the display must reflect routing, not the bare (misleading) type.
        story = _make_story(
            id="story-001",
            status="in-progress",
            acceptance_execution={"type": "manual", "command": "pytest tests/x.py"},
        )
        output = acceptance_types.format_acceptance_types({"stories": [story]})
        self.assertIn("story-001: manual (automated)", output)

    def test_manual_block_with_commands_plural_shows_automated_routing(self):
        # story-021/026: verify_acceptance routes on presence of `command`
        # OR `commands` (plural). The display check must mirror that, or a
        # `commands`-plural manual block is mislabeled as a walkthrough.
        story = _make_story(
            id="story-001",
            status="in-progress",
            acceptance_execution={
                "type": "manual",
                "commands": ["pytest tests/x.py", "pytest tests/y.py"],
            },
        )
        output = acceptance_types.format_acceptance_types({"stories": [story]})
        self.assertIn("story-001: manual (automated)", output)

    def test_command_less_block_shows_walkthrough(self):
        # No acceptance_execution → a manual walkthrough (command-less).
        story = _make_story(id="story-001", status="in-progress")
        output = acceptance_types.format_acceptance_types({"stories": [story]})
        self.assertIn("story-001: manual (walkthrough)", output)


if __name__ == "__main__":
    unittest.main()
