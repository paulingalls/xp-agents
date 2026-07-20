#!/usr/bin/env python3
"""Tests for sprint_schema.py field-level validators.

Covers: branch_name (sprint + story), execution_mode, executor_model,
executor_effort, empty_sprint, and the per-AC surface FK. Core
validate_sprint and acceptance-criteria item shape tests live in
test_sprint_schema.py — split for the 500-line cap.
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

    def test_branch_name_trailing_newline_rejected(self):
        """Python's `$` also matches BEFORE a trailing newline, so the pattern
        anchored with `$` accepted "main\\n". branch_name becomes a `git merge
        <ref>` argument and is interpolated into the story-close preload's
        KEY=value contract, where a newline forges a line at column 0."""
        sprint = _make_sprint(branch_name="t/sprint-001-g\n")
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

    def test_executor_model_fable_valid(self):
        """sprint-close finding C3: spawn_teammate.py --model accepts any string
        the harness recognizes (incl. 'fable'). The validator must include
        every tier spawn_teammate can forward, else `executor_model: 'fable'`
        would be rejected at save_sprint while the spawn would have worked."""
        story = _make_story(executor_model="fable")
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
            frozenset({"sonnet", "opus", "haiku", "fable"}),
        )


class TestStoryExecutorEffortField(unittest.TestCase):
    """Optional executor_effort story field: a reasoning-effort level or absent.

    Set by /xp-assign from the plan-reviewer's recommended_effort; forwarded to
    spawn_teammate's --effort flag. Validated at write time (like executor_model)
    so a garbage effort can't be persisted and silently forwarded.
    """

    def test_executor_effort_absent_valid(self):
        errors = sprint_schema.validate_sprint(_make_sprint())
        self.assertEqual(errors, [])

    def test_executor_effort_null_valid(self):
        sprint = _make_sprint(stories=[_make_story(executor_effort=None)])
        self.assertEqual(sprint_schema.validate_sprint(sprint), [])

    def test_executor_effort_known_level_valid(self):
        for level in ("low", "medium", "high", "xhigh", "max"):
            sprint = _make_sprint(stories=[_make_story(executor_effort=level)])
            self.assertEqual(sprint_schema.validate_sprint(sprint), [], level)

    def test_executor_effort_unknown_value_rejected(self):
        sprint = _make_sprint(stories=[_make_story(executor_effort="turbo")])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(
            any("executor_effort" in e and "turbo" in e for e in errors), errors
        )

    def test_executor_effort_non_string_rejected(self):
        sprint = _make_sprint(stories=[_make_story(executor_effort=3)])
        errors = sprint_schema.validate_sprint(sprint)
        self.assertTrue(any("executor_effort" in e for e in errors), errors)


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
