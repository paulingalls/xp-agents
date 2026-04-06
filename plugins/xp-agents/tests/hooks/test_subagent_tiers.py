#!/usr/bin/env python3
"""Tests for SubagentStart tiered context injection.

Split from test_subagent.py to stay under 500-line cap.
Covers: tiered SMM injection, pillar filtering, sprint context.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event

# ===========================================================================
# subagent_start.py core tests (moved from test_subagent.py)
# ===========================================================================


class TestSubagentStart(_HookTestCase):
    def test_xp_agent_skips(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_missing_smm_dir(self):
        import subagent_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_returns_values_without_smm_file(self):
        """Without curated SMM file, non-Explore agent still gets XP values."""
        import subagent_start

        self._write_events([make_event()])
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        # Non-Explore agent gets XP values even without SMM
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

    def test_reads_curated_smm_from_disk(self):
        """M5: SubagentStart reads curated SMM from disk when available."""
        import subagent_start

        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text("# Shared Mental Model\n\n## Intent\n- Ship v1\n")
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)

    def test_empty_events_still_gets_values(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        # Non-Explore agent gets XP values even with empty events
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

    def test_default_agent_id(self):
        """Default agent_id is 'subagent' — used in start event."""
        import subagent_start

        self._write_events([make_event()])
        subagent_start.run(
            {"session_id": "test"},
            smm_dir=self.smm_dir,
        )
        # Start event should use "subagent" as default agent_id
        events = self._read_events()
        start_events = [
            e for e in events if "Subagent subagent started" in e.get("content", "")
        ]
        self.assertEqual(len(start_events), 1)

    def test_falls_back_to_values_without_smm_file(self):
        """Without curated SMM, non-Explore agent gets XP values."""
        import subagent_start

        self._write_events([make_event("goal", content="Ship v1")])
        # No SHARED_MENTAL_MODEL.md on disk
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)


class TestSubagentStartEvent(_HookTestCase):
    """Tests for SubagentStart event recording (async agent timing fix)."""

    def test_start_records_status_event(self):
        import subagent_start

        self._write_events([make_event()])
        subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        events = self._read_events()
        # Should have original event + new start event
        self.assertEqual(len(events), 2)
        start_ev = events[1]
        self.assertEqual(start_ev["type"], "status")
        self.assertEqual(start_ev["agent_id"], "explorer-1")
        self.assertEqual(start_ev["content"], "Subagent explorer-1 started")

    def test_xp_agent_no_event(self):
        import subagent_start

        self._write_events([make_event()])
        subagent_start.run(
            {
                "session_id": "test",
                "agent_id": "xp-nav-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        events = self._read_events()
        # xp- agents should not write start events
        self.assertEqual(len(events), 1)


# ===========================================================================
# SubagentStart tiered injection tests (moved from test_subagent.py)
# ===========================================================================


class TestSubagentStartTieredInjection(_HookTestCase):
    """SubagentStart injects tiered context based on agent type."""

    def setUp(self):
        super().setUp()
        import subagent_start

        self.subagent_start = subagent_start
        # Write a curated SMM with all four pillars
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text(
            "# Shared Mental Model\n\n"
            "## Intent\n- Ship v1\n\n"
            "## Constraints\n- Python 3.10+ only\n\n"
            "## Risks\n- Auth module fragile\n\n"
            "## Wisdom\n- TDD always\n"
        )

    def test_explore_gets_only_intent_and_constraints(self):
        """Explore agent gets Intent + Constraints only."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "explore-1",
                "agent_type": "Explore",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Ship v1", result)
        self.assertIn("Constraints", result)
        self.assertIn("Python 3.10+", result)
        self.assertNotIn("Risks", result)
        self.assertNotIn("Auth module fragile", result)
        self.assertNotIn("Wisdom", result)
        self.assertNotIn("TDD always", result)

    def test_explore_no_behavioral_guide(self):
        """Explore agent does not get the behavioral guide."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "explore-1",
                "agent_type": "Explore",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("BEHAVIORAL_GUIDE", result)

    def test_general_agent_gets_full_smm_and_values(self):
        """General-purpose agent gets full SMM + XP values (no process guide)."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertIn("Risks", result)
        self.assertIn("Wisdom", result)
        self.assertIn("XP Values", result)
        self.assertNotIn("EnterPlanMode", result)

    def test_plan_agent_gets_full_smm_and_values(self):
        """Plan agent gets full SMM + XP values (no process guide)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("XP Values", result)
        self.assertNotIn("EnterPlanMode", result)
        self.assertIn("Constraints", result)
        self.assertIn("Risks", result)
        self.assertIn("Wisdom", result)

    def test_explore_wraps_in_smm_context(self):
        """Explore injection is wrapped in <smm-context> tags."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "explore-1",
                "agent_type": "Explore",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("<smm-context>", result)
        self.assertIn("</smm-context>", result)


# ===========================================================================
# Sprint-aware tier tests (M10)
# ===========================================================================

_SAMPLE_SPRINT = """\
# Sprint: Build user management REST API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: User registration
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001

### story-003: Admin user list
- **Size:** S
- **Status:** ready
- **Dependencies:** story-001
"""


class TestSubagentStartSprintTiers(_HookTestCase):
    """M10: Sprint-aware tiered injection."""

    def setUp(self):
        super().setUp()
        import subagent_start

        self.subagent_start = subagent_start
        smm_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        smm_file.write_text(
            "# Shared Mental Model\n\n"
            "## Intent\n- Ship v1\n\n"
            "## Constraints\n- Python 3.10+ only\n\n"
            "## Risks\n- Auth module fragile\n\n"
            "## Wisdom\n- TDD always\n"
        )
        sprint_file = self.smm_dir / "sprint.md"
        sprint_file.write_text(_SAMPLE_SPRINT)

    def test_plan_reviewer_gets_smm_and_sprint(self):
        """Plan reviewer (xp-plan-reviewer) gets full SMM + sprint.md."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("sprint-001", result)
        self.assertIn("story-002", result)

    def test_retrospective_gets_smm_and_sprint(self):
        """Retrospective (xp-retrospective) gets full SMM + sprint.md."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "retro-1",
                "agent_type": "xp-retrospective",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("sprint-001", result)

    def test_spawn_team_gets_smm_and_sprint(self):
        """Spawn team (xp-spawn-team) gets full SMM + sprint.md."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "spawn-1",
                "agent_type": "xp-spawn-team",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("sprint-001", result)

    def test_sprint_reviewer_gets_smm_and_sprint(self):
        """Sprint reviewer (xp-sprint-reviewer) gets full SMM + sprint."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "review-1",
                "agent_type": "xp-sprint-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("sprint-001", result)

    def test_sprint_retro_gets_smm_and_sprint(self):
        """Sprint retro (xp-sprint-retro) gets full SMM + sprint."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "retro-1",
                "agent_type": "xp-sprint-retro",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("sprint-001", result)

    def test_teammate_gets_smm_and_guide(self):
        """Teammate gets SMM + teammate guide (stories via spawn prompt)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "teammate-1",
                "agent_type": "backend-worker",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertIn("Teammate Guide", result)
        # Sprint stories NOT injected — come via spawn prompt instead
        self.assertNotIn("sprint-001", result)

    def test_teammate_no_metadata_gets_smm_only(self):
        """Agent without assigned_stories gets default (full SMM + guide)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "teammate-1",
                "agent_type": "general-purpose",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        # No sprint content without assigned_stories
        self.assertNotIn("sprint-001", result)

    def test_missing_sprint_degrades_gracefully(self):
        """Plan reviewer without sprint.md still gets SMM, no error."""
        (self.smm_dir / "sprint.md").unlink()
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertNotIn("sprint-001", result)

    def test_other_xp_agents_still_skipped(self):
        """xp-* agents not in dispatch table return None."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "nav-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_explore_unchanged(self):
        """Explore still gets Intent + Constraints only, no sprint."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "explore-1",
                "agent_type": "Explore",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertNotIn("sprint-001", result)

    def test_default_agent_unchanged(self):
        """Default (non-xp, non-Explore) gets full SMM + guide, no sprint."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Risks", result)
        self.assertNotIn("sprint-001", result)


if __name__ == "__main__":
    unittest.main()
