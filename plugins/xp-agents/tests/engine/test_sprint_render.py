#!/usr/bin/env python3
"""Tests for sprint_render.py — markdown rendering of sprint dicts.

Split from test_sprint_store.py at the commit that extracted
sprint_render. Render functions were moved unchanged from sprint_store
but get their own test file per the refactor-mode wisdom: a new module
gets at least one behavior test against its own surface, not via the
re-export shim.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)


class TestRenderMarkdown(unittest.TestCase):
    def test_render_includes_goal(self):
        import sprint_render

        md = sprint_render.render_markdown(_make_sprint(goal="Build auth"))
        self.assertIn("# Sprint: Build auth", md)

    def test_render_includes_story(self):
        import sprint_render

        md = sprint_render.render_markdown(_make_sprint())
        self.assertIn("### story-001: User registration", md)
        self.assertIn("**Status:** ready", md)

    def test_render_includes_sprint_id(self):
        import sprint_render

        md = sprint_render.render_markdown(_make_sprint())
        self.assertIn("sprint-001", md)

    def test_render_includes_executor_model_when_set(self):
        """sprint-close finding C4: durable schema slots (executor_model,
        execution_mode) must surface in render output so the lead can audit
        per-story tier and mode without raw JSON inspection."""
        import sprint_render

        story = _make_story(executor_model="opus", execution_mode="teammate")
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        self.assertIn("opus", md)
        self.assertIn("teammate", md)

    def test_render_omits_executor_model_when_absent(self):
        """When executor_model is absent/null, no `**Executor Model:**` line —
        match the existing pattern for milestone_ref / context / etc."""
        import sprint_render

        story = _make_story()  # no executor_model, no execution_mode
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        self.assertNotIn("Executor Model", md)
        self.assertNotIn("Execution Mode", md)

    def test_render_acceptance_execution(self):
        import sprint_render

        ae = {
            "type": "pytest",
            "command": "pytest tests/acceptance/",
            "setup": "docker compose up -d",
            "notes": "Requires backend on :3000",
        }
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        md = sprint_render.render_markdown(sprint)
        self.assertIn("**Acceptance Execution:**", md)
        self.assertIn("**Type:** pytest", md)
        self.assertIn("`pytest tests/acceptance/`", md)
        self.assertIn("`docker compose up -d`", md)
        self.assertIn("Requires backend on :3000", md)

    def test_render_acceptance_execution_minimal(self):
        import sprint_render

        ae = {"type": "bash", "command": "bash test.sh"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        md = sprint_render.render_markdown(sprint)
        self.assertIn("**Type:** bash", md)
        self.assertIn("`bash test.sh`", md)
        self.assertNotIn("**Setup:**", md)
        self.assertNotIn("**Notes:**", md)

    def test_render_no_acceptance_execution(self):
        import sprint_render

        md = sprint_render.render_markdown(_make_sprint())
        self.assertNotIn("Acceptance Execution", md)


class TestRenderStorySections(unittest.TestCase):
    def test_render_specific_stories(self):
        import sprint_render

        sprint = _make_sprint(
            stories=[
                _make_story(id="story-001", title="First"),
                _make_story(id="story-002", title="Second"),
                _make_story(id="story-003", title="Third"),
            ]
        )
        md = sprint_render.render_story_sections(sprint, ["story-001", "story-003"])
        self.assertIn("story-001", md)
        self.assertIn("First", md)
        self.assertIn("story-003", md)
        self.assertIn("Third", md)
        self.assertNotIn("story-002", md)

    def test_empty_ids_returns_empty(self):
        import sprint_render

        md = sprint_render.render_story_sections(_make_sprint(), [])
        self.assertEqual(md, "")


class TestRenderAcceptanceCriteriaItems(unittest.TestCase):
    """String AC items render unchanged; object AC items show description
    plus their verify command(s)."""

    def test_string_criteria_render_as_bullets(self):
        import sprint_render

        story = _make_story(acceptance_criteria=["Users can register"])
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        self.assertIn("- Users can register", md)

    def test_object_criterion_renders_description_and_command(self):
        import sprint_render

        ac = [{"description": "exports CSV", "command": "pytest tests/test_x.py"}]
        story = _make_story(acceptance_criteria=ac)
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        # No raw dict repr leaks into the markdown.
        self.assertNotIn("{'description'", md)
        self.assertIn("- exports CSV", md)
        self.assertIn("`pytest tests/test_x.py`", md)

    def test_object_criterion_renders_each_command_in_list(self):
        import sprint_render

        ac = [
            {
                "description": "pipeline green",
                "commands": ["grep -q FOO f.txt", "pytest tests/test_y.py"],
            }
        ]
        story = _make_story(acceptance_criteria=ac)
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        self.assertNotIn("{'description'", md)
        self.assertIn("- pipeline green", md)
        self.assertIn("`grep -q FOO f.txt`", md)
        self.assertIn("`pytest tests/test_y.py`", md)

    def test_string_only_render_unchanged_by_object_support(self):
        import sprint_render

        story = _make_story(
            acceptance_criteria=["Users can register", "E2E: registration flow"]
        )
        md = sprint_render.render_markdown(_make_sprint(stories=[story]))
        # Byte-identical to the pre-object render: the AC section is exactly
        # the header followed by one `- {text}` bullet per string item, with
        # no indented command rows. Pin the whole block, not scattered lines.
        expected_block = (
            "**Acceptance Criteria:**\n- Users can register\n- E2E: registration flow\n"
        )
        self.assertIn(expected_block, md)


if __name__ == "__main__":
    unittest.main()
