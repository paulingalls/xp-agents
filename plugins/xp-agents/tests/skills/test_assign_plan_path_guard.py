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

    def test_no_target_emits_plan_unguarded(self):
        """Empty batch (no un-spawned story) -> target empty -> emit as today."""
        plan_path = self._write_plan("# story-005: Some other story\n\nDetails.\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "PLAN_FILE"), str(plan_path)
        )


if __name__ == "__main__":
    unittest.main()
