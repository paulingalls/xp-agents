#!/usr/bin/env python3
"""story-004: xp-assign preload's PLAN_FILE guard against a stale plan path.

`.last-plan-path` holds only a path (no story id) and is overwritten by every
/xp-review-plan, so if the lead plans several stories before assigning, it
names the LATEST plan while the assign target is the lowest un-spawned story.
The preload must only emit PLAN_FILE when the plan's H1 either declares no
owning story (free-form, can't attribute) or matches the resolved target.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from conftest import _extract_preload_var, _IntegrationTestCase, _s, _sprint_json

_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestAssignPlanPathGuard(_IntegrationTestCase):
    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def _write_plan(self, text: str) -> Path:
        plan_path = self.smm_dir / "plan.md"
        plan_path.write_text(text)
        (self.smm_dir / ".last-plan-path").write_text(str(plan_path))
        return plan_path

    def _single_teammate_sprint(self, story_id: str = "story-004") -> str:
        return _sprint_json(
            [_s(story_id, "Guard plan path", "in-progress", execution_mode="teammate")]
        )

    def test_matching_plan_is_emitted(self):
        """Plan H1 names the target story -> PLAN_FILE emitted (behavior-preserving)."""
        self._write_sprint(self._single_teammate_sprint("story-004"))
        plan_path = self._write_plan("# story-004: Guard plan path\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "PLAN_FILE"), str(plan_path)
        )

    def test_stale_plan_for_another_story_is_suppressed(self):
        """Plan H1 names a DIFFERENT story than the target -> PLAN_FILE suppressed."""
        self._write_sprint(self._single_teammate_sprint("story-004"))
        self._write_plan("# story-005: Some other story\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(_extract_preload_var(result.stdout, "PLAN_FILE"))

    def test_free_form_plan_with_no_story_h1_is_emitted(self):
        """No story-titled H1 -> can't attribute -> emit unguarded (no
        false-negative)."""
        self._write_sprint(self._single_teammate_sprint("story-004"))
        plan_path = self._write_plan("# Ad-hoc plan\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "PLAN_FILE"), str(plan_path)
        )

    def test_unresolvable_target_suppresses_a_story_titled_plan(self):
        """No resolvable target -> fail CLOSED on a plan that names a story.

        The target is empty when the batch is empty AND when the resolution
        itself broke (the preload's Python block is `2>/dev/null`, so a failure
        there is indistinguishable from an empty batch). Emitting then hands
        over the exact stale plan this guard exists to suppress, on the path
        where resolution is already known to be unhealthy — so a plan that
        declares an owning story is withheld unless that story IS the target.
        """
        self._write_plan("# story-005: Some other story\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(_extract_preload_var(result.stdout, "PLAN_FILE"))

    def test_unresolvable_target_still_emits_a_free_form_plan(self):
        """Fail-closed is scoped to plans that CLAIM an owner. A plan with no
        story-titled H1 was never attributable, so withholding it would be a
        false negative, not a guard."""
        plan_path = self._write_plan("# Ad-hoc plan\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "PLAN_FILE"), str(plan_path)
        )

    def test_story_id_quoted_below_the_h1_does_not_suppress(self):
        """The guard keys on the H1, not on any `# story-NNN` line anywhere.

        A plan quoting a commit message or a fenced snippet that happens to
        start `# story-NNN` would otherwise be read as a plan for that story
        and withheld — a hard stop on a plan that is in fact the right one.
        """
        self._write_sprint(self._single_teammate_sprint("story-004"))
        plan_path = self._write_plan(
            "# Guard plan path\n\nPrior commit:\n\n```\n# story-005: other\n```\n"
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "PLAN_FILE"), str(plan_path)
        )

    def test_matching_h1_wins_over_another_story_mentioned_later(self):
        """Symmetric: an H1 naming the target is not undone by a later mention
        of a different story, and a later mention of the TARGET does not
        rescue an H1 that names someone else."""
        self._write_sprint(self._single_teammate_sprint("story-004"))
        self._write_plan("# story-005: other story\n\nSupersedes story-004.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(_extract_preload_var(result.stdout, "PLAN_FILE"))


if __name__ == "__main__":
    unittest.main()
