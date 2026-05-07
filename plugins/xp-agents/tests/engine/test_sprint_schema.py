#!/usr/bin/env python3
"""Tests for sprint_schema.py validation logic.

Covers: validate_sprint, branch_name field, empty_sprint, story validation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_schema
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)


class TestValidateSprint(unittest.TestCase):
    def test_valid_sprint_no_errors(self):
        errors = sprint_schema.validate_sprint(_make_sprint())
        self.assertEqual(errors, [])

    def test_not_a_dict(self):
        errors = sprint_schema.validate_sprint("not a dict")
        self.assertIn("must be an object", errors[0])

    def test_missing_required_fields(self):
        errors = sprint_schema.validate_sprint({})
        for field in ("sprint_id", "goal", "started", "stories"):
            self.assertTrue(
                any(field in e for e in errors),
                f"Missing error for {field}",
            )

    def test_invalid_story_status(self):
        sprint = _make_sprint(stories=[_make_story(status="bogus")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("status" in e for e in errors))

    def test_valid_statuses(self):
        for status in (
            "ready",
            "scheduled",
            "in-progress",
            "reviewing",
            "closing",
            "done",
            "deferred",
        ):
            sprint = _make_sprint(stories=[_make_story(status=status)])
            errors = sprint_schema.validate_sprint(sprint)
            self.assertEqual(errors, [], f"Status {status!r} should be valid")

    def test_scheduled_is_active_not_terminal(self):
        # `scheduled` sits between ready and in-progress — both ACTIVE,
        # neither TERMINAL. Stop gates / accept-cycle distinguish on terminal,
        # not on the specific value.
        self.assertIn("scheduled", sprint_schema.VALID_STORY_STATUSES)
        self.assertIn("scheduled", sprint_schema.ACTIVE_STORY_STATUSES)
        self.assertNotIn("scheduled", sprint_schema.TERMINAL_STORY_STATUSES)

    def test_reviewing_is_active_not_terminal(self):
        # `reviewing` sits between in-progress and done/deferred — under
        # acceptance verification but not yet terminal. Hooks gating on
        # `has_in_progress_stories` deliberately do NOT treat reviewing as
        # actively-worked (preserves the .accept marker re-arm carve-out);
        # but schema-wise it's still ACTIVE.
        self.assertIn("reviewing", sprint_schema.VALID_STORY_STATUSES)
        self.assertIn("reviewing", sprint_schema.ACTIVE_STORY_STATUSES)
        self.assertNotIn("reviewing", sprint_schema.TERMINAL_STORY_STATUSES)

    def test_closing_is_active_not_terminal(self):
        # `closing` sits between reviewing and done — sprint-singleton,
        # marks the one story currently inside /xp-story-close pipeline.
        # ACTIVE (not TERMINAL) so cascade-defer + orphan-set treat it
        # like other in-motion states.
        self.assertIn("closing", sprint_schema.VALID_STORY_STATUSES)
        self.assertIn("closing", sprint_schema.ACTIVE_STORY_STATUSES)
        self.assertNotIn("closing", sprint_schema.TERMINAL_STORY_STATUSES)

    def test_in_motion_membership(self):
        # IN_MOTION = stories with work in motion: branched + actively
        # edited or under acceptance verification. Drives cascade-deferral
        # (transitive_active_dependents) and orphan-branch active-set.
        # Pre-branch states (ready, scheduled) and terminal states
        # (done, deferred) are excluded.
        for in_motion in ("in-progress", "reviewing", "closing"):
            self.assertIn(
                in_motion,
                sprint_schema.IN_MOTION_STORY_STATUSES,
                f"{in_motion!r} should be in IN_MOTION",
            )
        for not_in_motion in ("ready", "scheduled", "done", "deferred"):
            self.assertNotIn(
                not_in_motion,
                sprint_schema.IN_MOTION_STORY_STATUSES,
                f"{not_in_motion!r} should NOT be in IN_MOTION",
            )

    def test_story_missing_required_fields(self):
        sprint = _make_sprint(stories=[{"id": "story-001"}])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertGreater(len(errors), 0)

    def test_stories_must_be_list(self):
        errors = sprint_schema.validate_sprint(_make_sprint(stories="not list"))
        self.assertTrue(any("stories" in e for e in errors))

    def test_acceptance_execution_valid(self):
        ae = {"type": "pytest", "command": "pytest tests/acceptance/"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_with_all_fields(self):
        ae = {
            "type": "playwright",
            "command": "npx playwright test",
            "setup": "docker compose up -d",
            "notes": "Requires backend on :3000",
        }
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_absent_is_valid(self):
        sprint = _make_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_acceptance_execution_missing_type_fails(self):
        ae = {"command": "pytest tests/"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("type" in e for e in errors))

    def test_acceptance_execution_missing_command_fails(self):
        ae = {"type": "pytest"}
        sprint = _make_sprint(stories=[_make_story(acceptance_execution=ae)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("command" in e for e in errors))

    def test_acceptance_execution_not_dict_fails(self):
        sprint = _make_sprint(stories=[_make_story(acceptance_execution="bad")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("acceptance_execution" in e for e in errors))


class TestBranchNameField(unittest.TestCase):
    def test_branch_name_string_valid(self):
        sprint = _make_sprint(branch_name="paul/sprint-031-test")
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_branch_name_null_valid(self):
        sprint = _make_sprint(branch_name=None)
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_branch_name_missing_valid(self):
        sprint = _make_sprint()
        sprint.pop("branch_name", None)
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_branch_name_non_string_invalid(self):
        sprint = _make_sprint(branch_name=42)
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("branch_name" in e for e in errors))

    def test_branch_name_invalid_format_rejected(self):
        sprint = _make_sprint(branch_name="has spaces/bad")
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("valid git branch name" in e for e in errors))


class TestStoryBranchNameField(unittest.TestCase):
    def test_story_without_branch_name_valid(self):
        sprint = _make_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_story_branch_name_string_valid(self):
        story = _make_story(branch_name="paul/story-001-foo")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_story_branch_name_null_valid(self):
        story = _make_story(branch_name=None)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_story_branch_name_non_string_invalid(self):
        story = _make_story(branch_name=42)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("branch_name" in e for e in errors))

    def test_story_branch_name_invalid_format_rejected(self):
        story = _make_story(branch_name="has spaces/bad")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("valid git branch name" in e for e in errors))


class TestEmptySprint(unittest.TestCase):
    def test_empty_sprint_is_valid(self):
        sprint = sprint_schema.empty_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_has_required_fields(self):
        sprint = sprint_schema.empty_sprint()
        for field in ("sprint_id", "goal", "started", "stories"):
            self.assertIn(field, sprint)


if __name__ == "__main__":
    unittest.main()
