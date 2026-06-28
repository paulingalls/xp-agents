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
from conftest import _SMMTestCase
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

    def test_under_acceptance_is_reviewing_and_closing(self):
        # UNDER_ACCEPTANCE = the close-then-done window: stories that
        # have left in-progress and are inside the per-story accept
        # dispatch (xp-accept → xp-story-close → mark-done). Subset of
        # IN_MOTION (which also includes in-progress).
        self.assertEqual(
            sprint_schema.UNDER_ACCEPTANCE_STORY_STATUSES,
            frozenset({"reviewing", "closing"}),
        )
        self.assertTrue(
            sprint_schema.UNDER_ACCEPTANCE_STORY_STATUSES.issubset(
                sprint_schema.IN_MOTION_STORY_STATUSES
            )
        )
        self.assertNotIn("in-progress", sprint_schema.UNDER_ACCEPTANCE_STORY_STATUSES)

    def test_validate_sprint_accepts_closing_status(self):
        # AC3: sprint.json with a story at status 'closing' validates
        # with no errors. Pinned as a dedicated test (not just iterated
        # via test_valid_statuses) so an AC-trace grep finds the named
        # case directly.
        sprint = _make_sprint(stories=[_make_story(status="closing")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

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


class TestAcceptanceCriteriaItemShape(unittest.TestCase):
    """AC items may be a bare string (manual) or a per-AC verify object."""

    def test_string_only_criteria_valid(self):
        sprint = _make_sprint(
            stories=[_make_story(acceptance_criteria=["Users can register"])]
        )
        self.assertEqual(sprint_schema.validate_sprint(sprint), [])

    def test_object_criteria_item_valid(self):
        ac = [
            "Users can register",
            {"description": "exports CSV", "surface": "cli", "command": "pytest x"},
        ]
        sprint = _make_sprint(stories=[_make_story(acceptance_criteria=ac)])
        self.assertEqual(sprint_schema.validate_sprint(sprint), [])

    def test_malformed_object_criteria_surfaced_with_index_prefix(self):
        ac = [
            "ok",
            {"description": "x", "command": "c", "commands": ["c"]},
        ]
        sprint = _make_sprint(stories=[_make_story(acceptance_criteria=ac)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("acceptance_criteria[1]" in e for e in errors), errors)

    def test_object_missing_description_rejected(self):
        ac = [{"command": "pytest x"}]
        sprint = _make_sprint(stories=[_make_story(acceptance_criteria=ac)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("description" in e for e in errors), errors)

    def test_non_string_non_dict_criteria_rejected(self):
        sprint = _make_sprint(stories=[_make_story(acceptance_criteria=[42])])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("acceptance_criteria[0]" in e for e in errors), errors)


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


class TestStoryExecutionModeField(unittest.TestCase):
    """Optional execution_mode story field: "solo" | "teammate" | absent.

    Set by /xp-schedule when it promotes a frontier; read by the
    plan-review gate (subagent_stop) to decide whether to arm
    .assign-pending. Optional — absent is valid (pre-promotion stories).
    """

    def test_story_without_execution_mode_valid(self):
        sprint = _make_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_execution_mode_solo_valid(self):
        story = _make_story(execution_mode="solo")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_execution_mode_teammate_valid(self):
        story = _make_story(execution_mode="teammate")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_execution_mode_null_valid(self):
        story = _make_story(execution_mode=None)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_execution_mode_unknown_value_rejected(self):
        story = _make_story(execution_mode="parallel")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(
            any("execution_mode" in e and "parallel" in e for e in errors), errors
        )

    def test_execution_mode_non_string_rejected(self):
        story = _make_story(execution_mode=2)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("execution_mode" in e for e in errors), errors)

    def test_valid_execution_modes_constant(self):
        self.assertEqual(
            sprint_schema.VALID_EXECUTION_MODES, frozenset({"solo", "teammate"})
        )


class TestStoryExecutorModelField(unittest.TestCase):
    """Optional executor_model story field: "sonnet" | "opus" | "haiku" | absent.

    Set by the lead during per-story planning (M2 reshape); read by
    /xp-assign to forward to spawn_teammate's --model flag. Optional —
    absent means inherit the lead's model.
    """

    def test_story_without_executor_model_valid(self):
        sprint = _make_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_executor_model_sonnet_valid(self):
        story = _make_story(executor_model="sonnet")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_executor_model_opus_valid(self):
        story = _make_story(executor_model="opus")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_executor_model_haiku_valid(self):
        story = _make_story(executor_model="haiku")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_executor_model_null_valid(self):
        story = _make_story(executor_model=None)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_executor_model_unknown_value_rejected(self):
        story = _make_story(executor_model="gpt5")
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(
            any("executor_model" in e and "gpt5" in e for e in errors), errors
        )

    def test_executor_model_non_string_rejected(self):
        story = _make_story(executor_model=2)
        sprint = _make_sprint(stories=[story])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("executor_model" in e for e in errors), errors)

    def test_valid_executor_models_constant(self):
        self.assertEqual(
            sprint_schema.VALID_EXECUTOR_MODELS,
            frozenset({"sonnet", "opus", "haiku"}),
        )


class TestExecutorModelStoreRoundTrip(_SMMTestCase):
    """E2E coverage for story-002 AC #3: a story's executor_model survives
    save_sprint → load_sprint round-trip via the existing shallow-merge path."""

    def test_executor_model_round_trips_through_store(self):
        import sprint_store

        sprint = _make_sprint(stories=[_make_story(executor_model="opus")])
        sprint_store.save_sprint(self.smm_dir, sprint)
        loaded = sprint_store.load_sprint(self.smm_dir)
        assert loaded is not None
        self.assertEqual(loaded["stories"][0]["executor_model"], "opus")


class TestEmptySprint(unittest.TestCase):
    def test_empty_sprint_is_valid(self):
        sprint = sprint_schema.empty_sprint()
        errors = sprint_schema.validate_sprint(sprint)
        self.assertEqual(errors, [])

    def test_has_required_fields(self):
        sprint = sprint_schema.empty_sprint()
        for field in ("sprint_id", "goal", "started", "stories"):
            self.assertIn(field, sprint)


class TestValidateSprintSurfaceFK(unittest.TestCase):
    """validate_sprint threads valid_surfaces to the per-AC surface FK.
    None (default) keeps it shape-only; a frozenset turns it enforcing."""

    def _sprint_with_surface(self, surface: str) -> dict:
        story = _make_story(
            acceptance_criteria=[{"description": "works", "surface": surface}]
        )
        return _make_sprint(stories=[story])

    def test_known_surface_passes(self):
        sprint = self._sprint_with_surface("api")
        errors = sprint_schema.validate_sprint(
            sprint, valid_surfaces=frozenset({"api", "cli"})
        )
        self.assertEqual(errors, [])

    def test_unknown_surface_rejected(self):
        sprint = self._sprint_with_surface("ghost")
        errors = sprint_schema.validate_sprint(
            sprint, valid_surfaces=frozenset({"api", "cli"})
        )
        self.assertTrue(any("surface" in e and "ghost" in e for e in errors), errors)

    def test_none_valid_surfaces_skips_fk(self):
        sprint = self._sprint_with_surface("ghost")
        errors = sprint_schema.validate_sprint(sprint, valid_surfaces=None)
        self.assertEqual(errors, [])

    def test_default_is_shape_only(self):
        sprint = self._sprint_with_surface("ghost")
        self.assertEqual(sprint_schema.validate_sprint(sprint), [])

    def test_bare_string_acs_unaffected(self):
        sprint = _make_sprint(stories=[_make_story()])
        errors = sprint_schema.validate_sprint(
            sprint, valid_surfaces=frozenset({"api"})
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
