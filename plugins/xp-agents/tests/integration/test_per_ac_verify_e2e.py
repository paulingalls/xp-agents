#!/usr/bin/env python3
"""M-2 capstone: cross-schema per-AC verify + surfaces_touched, end-to-end.

Exercises Milestone-2 stories 001-003 through the CLIs and the schema:

  - story-001/002: sprint acceptance_criteria items may be a bare string
    (manual AC) or an object {description, surface?, command?|commands?};
    sprint_cli create validates them and render emits object items.
  - story-003: milestone.surfaces_touched is an optional list[str], FK to
    acceptance_surfaces[*].name when a valid_surfaces set is supplied
    (None = shape-only; FK enforcement deferred to the M3 caller).

Capstone discipline: stories 001-003 are already done, so these pass on
first write — the "red" they guard is a back-compat or schema regression,
not a red->green cycle. Back-compat is the headline: legacy string-only
sprints and surfaceless plans must still create and render unchanged.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from conftest import (
    _IntegrationTestCase,
    make_milestone_dict,
    make_plan_dict,
    make_sprint_dict,
    make_story_dict,
    run_cli,
)

_SPRINT_CLI = _PLUGIN_ROOT / "smm" / "sprint_cli.py"
_PLAN_CLI = _PLUGIN_ROOT / "smm" / "plan_cli.py"


class TestPerAcVerifyCapstone(_IntegrationTestCase):
    """End-to-end M-2 acceptance across sprint + plan schemas via the CLIs."""

    def _sprint_cli(self, args: list[str], stdin_data: str = "") -> tuple[int, str]:
        r = run_cli(_SPRINT_CLI, args, self.smm_dir, stdin_data=stdin_data)
        return r.returncode, r.stdout + r.stderr

    def _plan_cli(self, args: list[str], stdin_data: str = "") -> tuple[int, str]:
        r = run_cli(_PLAN_CLI, args, self.smm_dir, stdin_data=stdin_data)
        return r.returncode, r.stdout + r.stderr

    def _create_sprint(self, acceptance_criteria: list) -> tuple[int, str]:
        sprint = make_sprint_dict(
            stories=[make_story_dict(acceptance_criteria=acceptance_criteria)]
        )
        return self._sprint_cli(["create"], stdin_data=json.dumps(sprint))

    def _create_plan(self, **milestone_overrides) -> tuple[int, str]:
        plan = make_plan_dict(milestones=[make_milestone_dict(**milestone_overrides)])
        return self._plan_cli(["create"], stdin_data=json.dumps(plan))

    def test_object_ac_sprint_creates_and_renders(self) -> None:
        """An object-AC sprint validates on create and renders its
        description + verify command (no raw dict repr)."""
        ac = [
            "Users can register",
            {"description": "exports CSV", "surface": "cli", "command": "pytest x"},
        ]
        rc, _ = self._create_sprint(ac)
        self.assertEqual(rc, 0)

        rc, out = self._sprint_cli(["render"])
        self.assertEqual(rc, 0)
        self.assertIn("exports CSV", out)
        self.assertIn("pytest x", out)
        self.assertNotIn("{'description'", out)

    def test_surfaces_touched_plan_creates_and_renders(self) -> None:
        """A milestone with surfaces_touched validates on create and renders
        a Surfaces Touched line."""
        rc, _ = self._create_plan(surfaces_touched=["api", "cli"])
        self.assertEqual(rc, 0)

        rc, out = self._plan_cli(["render"])
        self.assertEqual(rc, 0)
        self.assertIn("Surfaces Touched", out)
        self.assertIn("api, cli", out)

    def test_legacy_string_only_sprint_still_creates(self) -> None:
        """Back-compat: a sprint whose ACs are all bare strings still
        validates and creates unchanged."""
        rc, _ = self._create_sprint(["a", "E2E: b"])
        self.assertEqual(rc, 0)
        rc, out = self._sprint_cli(["render"])
        self.assertEqual(rc, 0)
        self.assertIn("- a", out)
        self.assertIn("- E2E: b", out)

    def test_surfaceless_plan_still_creates(self) -> None:
        """Back-compat: a plan with no surfaces_touched validates and
        renders without a Surfaces Touched line."""
        rc, _ = self._create_plan()
        self.assertEqual(rc, 0)
        rc, out = self._plan_cli(["render"])
        self.assertEqual(rc, 0)
        self.assertNotIn("Surfaces Touched", out)

    def test_malformed_object_ac_rejected_on_create(self) -> None:
        """An object AC with both command and commands is rejected at
        create time — the per-AC validator is wired into sprint validation."""
        bad = [{"description": "x", "command": "c", "commands": ["c"]}]
        rc, out = self._create_sprint(bad)
        self.assertNotEqual(rc, 0)
        self.assertIn("acceptance_criteria", out)

    def test_surfaces_touched_fk_error_with_surface_set(self) -> None:
        """End-to-end FK: a plan + a known surface set (as the M3 caller
        supplies) yields an FK error naming the unknown surface."""
        import execution_plan_schema as schema

        plan = make_plan_dict(
            milestones=[make_milestone_dict(surfaces_touched=["api", "ghost"])]
        )
        errors = schema.validate_plan(plan, valid_surfaces=frozenset({"api", "cli"}))
        self.assertTrue(
            any("surfaces_touched" in e and "ghost" in e for e in errors), errors
        )
        # Same plan, no surface set → shape-only, no FK error.
        self.assertEqual(schema.validate_plan(plan), [])


if __name__ == "__main__":
    unittest.main()
