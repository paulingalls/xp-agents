#!/usr/bin/env python3
"""Tests for sprint_store.build_capstone_story.

The builder produces a deterministic, schema-valid capstone story dict:
ready status, Capstone-prefixed title, dependencies on all siblings, one
behavior-shaped object AC per touched surface, and an acceptance_execution
placeholder the implementer fills during the capstone's own story.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import make_sprint_dict as _make_sprint


class TestBuildCapstoneStory(unittest.TestCase):
    def _build(self, **overrides):
        import sprint_store

        kwargs = {
            "story_id": "story-006",
            "milestone_name": "Milestone 3: surface-coverage",
            "touched_surfaces": ["cli", "sdk"],
            "depends_on": ["story-001", "story-002"],
        }
        kwargs.update(overrides)
        return sprint_store.build_capstone_story(**kwargs)

    def test_ready_capstone_titled_and_depends_on_siblings(self):
        story = self._build()
        self.assertEqual(story["id"], "story-006")
        self.assertEqual(story["status"], "ready")
        self.assertTrue(story["title"].startswith("Capstone:"))
        self.assertIn("Milestone 3: surface-coverage", story["title"])
        self.assertEqual(story["dependencies"], ["story-001", "story-002"])

    def test_one_object_ac_per_surface_plus_placeholder(self):
        story = self._build(touched_surfaces=["cli", "sdk"])
        object_acs = [a for a in story["acceptance_criteria"] if isinstance(a, dict)]
        surfaces = {a["surface"] for a in object_acs}
        self.assertEqual(surfaces, {"cli", "sdk"})
        for a in object_acs:
            self.assertIn("description", a)
            self.assertIsInstance(a["description"], str)
        ae = story["acceptance_execution"]
        self.assertIsInstance(ae["type"], str)
        self.assertTrue(ae["command"])  # non-empty placeholder

    def test_includes_e2e_acceptance_criterion(self):
        story = self._build()
        texts = [
            a if isinstance(a, str) else a.get("description", "")
            for a in story["acceptance_criteria"]
        ]
        self.assertTrue(
            any(t.startswith("E2E:") for t in texts),
            f"expected an E2E-prefixed AC, got {texts}",
        )

    def test_appending_to_sprint_validates(self):
        import sprint_schema

        story = self._build()
        sprint = _make_sprint()
        sprint["stories"].append(story)
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [], errors)

    def test_empty_surfaces_still_valid_with_e2e(self):
        import sprint_schema

        story = self._build(touched_surfaces=[])
        self.assertTrue(story["acceptance_criteria"])  # at least the E2E
        sprint = _make_sprint()
        sprint["stories"].append(story)
        self.assertEqual(sprint_schema.validate_sprint(sprint), [])


if __name__ == "__main__":
    unittest.main()
