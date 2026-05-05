#!/usr/bin/env python3
"""Tests for per-field maxLength enforcement in sprint_schema.py.

Extracted from test_sprint_store.py to keep files under 500 lines.
Mirrors test_execution_plan_budgets.py structure.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _SMMTestCase,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)


class TestStoryFieldBudgets(unittest.TestCase):
    """Test per-field maxLength enforcement in validate_sprint()."""

    def test_context_over_budget_rejected(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(context="x" * 601)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(
            any("context" in e and "601" in e and "600" in e for e in errors)
        )

    def test_context_at_budget_accepted(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(context="x" * 600)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertFalse(any("context" in e and "budget" in e for e in errors))

    def test_file_domain_item_over_budget_rejected(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(file_domain=["x" * 201])])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(
            any("file_domain" in e and "201" in e and "200" in e for e in errors)
        )

    def test_file_domain_item_at_budget_accepted(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(file_domain=["x" * 200])])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertFalse(any("file_domain" in e and "budget" in e for e in errors))


class TestBudgetEnforceFlag(unittest.TestCase):
    """validate_sprint(enforce_budget=False) grandfathers over-budget fields."""

    def test_over_budget_accepted_when_not_enforced(self):
        import sprint_schema

        sprint = _make_sprint(
            stories=[
                _make_story(
                    context="x" * 800,
                    file_domain=["x" * 300],
                )
            ]
        )
        errors = sprint_schema.validate_sprint(sprint, enforce_budget=False)
        self.assertEqual(errors, [])

    def test_over_budget_rejected_when_enforced(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story(context="x" * 800)])
        errors = sprint_schema.validate_sprint(sprint, enforce_budget=True)
        self.assertTrue(any("budget" in e for e in errors))

    def test_structural_errors_still_caught_without_budget(self):
        import sprint_schema

        sprint = _make_sprint(stories=[_make_story()])
        sprint["stories"][0]["status"] = "bogus"
        errors = sprint_schema.validate_sprint(sprint, enforce_budget=False)
        self.assertTrue(any("status" in e for e in errors))


class TestLoadSprintGrandfathersBudget(_SMMTestCase):
    """load_sprint reads over-budget sprints; save_sprint rejects them."""

    def test_load_over_budget_sprint_succeeds(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(context="x" * 800)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        loaded = sprint_store.load_sprint(self.smm_dir)
        assert loaded is not None
        self.assertEqual(len(loaded["stories"][0]["context"]), 800)

    def test_save_over_budget_sprint_rejected(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(context="x" * 800)])
        with self.assertRaises(ValueError) as ctx:
            sprint_store.save_sprint(self.smm_dir, sprint)
        self.assertIn("budget", str(ctx.exception).lower())


class TestStatusUpdateGrandfathersBudget(_SMMTestCase):
    """Status-only updates must not fail on pre-existing over-budget content."""

    def test_update_story_status_succeeds_with_over_budget_context(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(context="x" * 800)])
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        sprint_store.update_story_status(self.smm_dir, "story-001", "done")
        loaded = sprint_store.load_sprint(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["stories"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
