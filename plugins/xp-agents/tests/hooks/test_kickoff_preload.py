#!/usr/bin/env python3
"""Tests for check_session_needs.sh: kickoff preload sprint-aware output."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_MIXED,
    _IntegrationTestCase,
)

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-kickoff"
    / "scripts"
    / "check_session_needs.sh"
)


class TestKickoffPreloadSprintAware(_IntegrationTestCase):
    """M8b: check_session_needs.sh outputs sprint marker and state info."""

    def test_outputs_needs_execution_plan_when_missing(self):
        """No execution_plan.json — emit NEEDS_EXECUTION_PLAN flag."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_EXECUTION_PLAN", result.stdout)

    def test_no_execution_plan_flag_when_active_plan(self):
        """execution_plan.json with remaining work — no flag."""
        import json

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M",
                    "status": "planned",
                    "delivered_sprint": None,
                    "goal": "G",
                    "done": "D",
                    "sources": "",
                    "change_zones": [],
                    "impact_zones": [],
                    "design_details": "",
                    "constraints": [],
                }
            ],
        }
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_EXECUTION_PLAN", result.stdout)

    def test_execution_plan_flag_when_all_delivered(self):
        """execution_plan.json with all delivered — emit flag."""
        import json

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M",
                    "status": "delivered",
                    "delivered_sprint": "sprint-001",
                    "goal": "G",
                    "done": "D",
                    "sources": "",
                    "change_zones": [],
                    "impact_zones": [],
                    "design_details": "",
                    "constraints": [],
                }
            ],
        }
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_EXECUTION_PLAN", result.stdout)

    def test_outputs_needs_sprint_when_marker_exists(self):
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_no_sprint_section_when_active_stories(self):
        """No marker, sprint.json with ready stories — no flag."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_needs_sprint_when_no_file(self):
        """No marker, no sprint.json — emit flag from file check."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_needs_sprint_when_all_done_no_marker(self):
        """No marker, sprint.json all done — emit flag."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SPRINT", result.stdout)

    def test_outputs_sprint_active_when_ready_stories(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_ACTIVE", result.stdout)
        self.assertIn("story-002", result.stdout)

    def test_no_sprint_active_when_no_sprint_file(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_sprint_active_when_all_done(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_ALL_DONE)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_no_markers_no_sprint(self):
        """No markers, no sprint/spec files — flags from file-existence."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)
        # File-existence checks emit flags even without markers
        self.assertIn("NEEDS_EXECUTION_PLAN", result.stdout)
        self.assertIn("NEEDS_SPRINT", result.stdout)
        self.assertNotIn("SPRINT_ACTIVE", result.stdout)

    def test_sprint_active_shows_only_ready_titles(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        # Ready stories should appear
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)
        # Counts line uses the four-state lifecycle format.
        self.assertIn("ready=2", result.stdout)
        self.assertIn("Ready:", result.stdout)

    def test_no_retro_marker_emitted(self):
        """Story-003: Step 1 is now unconditional; the preload no longer
        emits a RETRO_NEEDED marker for any input state. The action that
        the marker once gated lives in SKILL.md as 'always invoke', so
        the marker would only confuse the LLM by suggesting conditionality.
        """
        (self.smm_dir / ".retro-input.json").write_text('{"unanalyzed_count": 6}')
        (self.smm_dir / ".sprint-retro-input.json").write_text('{"sprint_id": "s-1"}')
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("RETRO_NEEDED", result.stdout)
        self.assertNotIn("SPRINT_RETRO_NEEDED", result.stdout)

    def test_outputs_needs_system_context_when_missing(self):
        """Reports NEEDS_SYSTEM_CONTEXT when system_context.json missing."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NEEDS_SYSTEM_CONTEXT", result.stdout)

    def test_no_system_context_flag_when_exists(self):
        """No flag when system_context.json exists."""
        (self.smm_dir / "system_context.json").write_text("{}")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("NEEDS_SYSTEM_CONTEXT", result.stdout)

    def test_outputs_stage_marker_when_system_context_exists(self):
        """Surfaces ### STAGE=N so SKILL.md Step 0 reads the stage from the
        preload instead of a redundant branching.py callback. Gated on a real
        system_context.json (which holds the stage)."""
        from _branching_fixtures import write_system_context

        write_system_context(self.smm_dir, stage=2)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### STAGE=2", result.stdout)

    def test_no_stage_marker_when_system_context_missing(self):
        """No ### STAGE marker when system_context.json is absent — the stage
        is meaningless (0) and the NEEDS_SYSTEM_CONTEXT path sets it instead."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("### STAGE", result.stdout)
        self.assertIn("NEEDS_SYSTEM_CONTEXT", result.stdout)

    def test_no_empty_stage_marker_when_branching_exits_nonzero(self):
        """A present-but-schema-invalid system_context.json on the stage-1
        auto-promote save path makes `branching.py stage` exit non-zero. The
        preload must (a) NOT emit an empty `### STAGE=` marker — which the SKILL
        would read as a valid STAGE<2 and falsely trigger /xp-stage-migration —
        and (b) survive set -e (exit 0) so the rest of kickoff still runs. No
        marker => SKILL falls back to the documented Python re-read."""
        # stage=1 read => auto-promote save => load_system_context revalidates
        # this minimal (invalid) doc and raises ValueError => stage exits 1.
        (self.smm_dir / "system_context.json").write_text(
            '{"branching_strategy": {"stage": 1}}'
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### STAGE=", result.stdout)
        # The file exists (non-symlink) so NEEDS_SYSTEM_CONTEXT must NOT fire.
        self.assertNotIn("NEEDS_SYSTEM_CONTEXT", result.stdout)

    def test_empty_marker_headers_carry_action_hint(self):
        """Empty-body markers must include the action they trigger inline.

        Why: an empty `### MARKER` heading reads as document structure and
        is easy to skim past, especially when the rest of the preload is
        heavy. Pinning the action hint into the heading keeps the trigger
        visually inseparable from its consequence.

        Story-003 dropped RETRO_NEEDED entirely (Step 1 is now
        unconditional), so only the three remaining gated markers are
        asserted here.
        """
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "### NEEDS_SYSTEM_CONTEXT → invoke /xp-system-context", result.stdout
        )
        self.assertIn("### NEEDS_EXECUTION_PLAN → invoke /xp-plan", result.stdout)
        self.assertIn("### NEEDS_SPRINT → invoke /xp-sprint-start", result.stdout)


if __name__ == "__main__":
    unittest.main()
