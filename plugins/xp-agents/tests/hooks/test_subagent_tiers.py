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

from conftest import SAMPLE_SPRINT_MD as _SAMPLE_SPRINT
from conftest import _HookTestCase, make_event, write_smm_fixture

# ===========================================================================
# subagent_start.py core tests (moved from test_subagent.py)
# ===========================================================================


class TestSubagentStart(_HookTestCase):
    def test_xp_agent_gets_values_only(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

    def test_missing_smm_dir_still_gets_values(self):
        import subagent_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1"},
            smm_dir=fake_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

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

        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
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

    def test_xp_agent_records_start_event(self):
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
        # xp-* agents now go through run() and record start events
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["agent_id"], "xp-nav-1")


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
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth module fragile", "concern", "problem")],
            wisdom=["TDD always"],
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


class TestSubagentStartSprintTiers(_HookTestCase):
    """M10: Sprint-aware tiered injection."""

    def setUp(self):
        super().setUp()
        import subagent_start

        self.subagent_start = subagent_start
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
            risks=[("Auth module fragile", "concern", "problem")],
            wisdom=["TDD always"],
        )
        sprint_file = self.smm_dir / "sprint.json"
        sprint_file.write_text(_SAMPLE_SPRINT)

    def test_plan_reviewer_gets_values_only(self):
        """xp-plan-reviewer gets XP values only (data from preload)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)
        # Should NOT get SMM content (that comes from preload)
        self.assertNotIn("Ship v1", result)

    def test_retrospective_gets_values_only(self):
        """xp-retrospective gets XP values only (data from preload)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "retro-1",
                "agent_type": "xp-retrospective",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)
        self.assertNotIn("Ship v1", result)

    def test_sprint_reviewer_gets_values_only(self):
        """xp-sprint-reviewer gets XP values only (data from preload)."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "review-1",
                "agent_type": "xp-sprint-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)
        self.assertNotIn("Ship v1", result)

    def test_custom_agent_type_gets_full_smm(self):
        """Custom agent types get full SMM (default tier), not teammate guide."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "worker-1",
                "agent_type": "backend-worker",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertNotIn("Teammate Guide", result)

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

    def test_plan_reviewer_no_sprint_still_gets_values(self):
        """xp-plan-reviewer gets values even without sprint.json."""
        (self.smm_dir / "sprint.json").unlink()
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

    def test_code_reviewer_gets_full_smm(self):
        """xp-code-reviewer gets full SMM (overrides xp-* default)."""
        for agent_type in ("xp-code-reviewer", "xp-agents:xp-code-reviewer"):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "reviewer-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                self.assertIsNotNone(result)
                self.assertIn("Intent", result)
                self.assertIn("Ship v1", result)
                self.assertIn("Constraints", result)
                self.assertIn("Python 3.10+", result)
                self.assertIn("Risks", result)
                self.assertIn("Wisdom", result)
                self.assertIn("XP Values", result)

    def test_other_xp_agents_get_values(self):
        """xp-* agents not in dispatch table still get XP values."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "nav-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)

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
