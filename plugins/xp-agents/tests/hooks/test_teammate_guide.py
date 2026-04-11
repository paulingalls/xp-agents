#!/usr/bin/env python3
"""Tests for M14: Teammate behavioral guide injection.

Covers: is_teammate_by_agent_type detection, teammate guide content,
non-teammate tiers unaffected.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import SAMPLE_SPRINT_MD as _SAMPLE_SPRINT
from conftest import _HookTestCase, write_smm_fixture


class TestTeammateDetection(unittest.TestCase):
    """M14: is_teammate_by_agent_type detection logic."""

    def setUp(self):
        import subagent_start

        self.is_teammate = subagent_start.is_teammate_by_agent_type

    def test_empty_agent_type_not_teammate(self):
        """Empty or missing agent_type is not a teammate."""
        self.assertFalse(self.is_teammate({}))
        self.assertFalse(self.is_teammate({"agent_type": ""}))

    def test_builtin_types_not_teammate(self):
        """Built-in agent types are not teammates."""
        for t in ("Explore", "Plan", "general-purpose", "Bash"):
            with self.subTest(agent_type=t):
                self.assertFalse(self.is_teammate({"agent_type": t}))

    def test_xp_prefixed_not_teammate(self):
        """Plugin xp-* agents are not teammates."""
        self.assertFalse(self.is_teammate({"agent_type": "xp-nav"}))
        self.assertFalse(self.is_teammate({"agent_type": "xp-retrospective"}))

    def test_custom_type_is_teammate(self):
        """Custom agent types are teammates."""
        self.assertTrue(self.is_teammate({"agent_type": "backend-worker"}))
        self.assertTrue(self.is_teammate({"agent_type": "frontend-dev"}))


class TestTeammateGuide(_HookTestCase):
    """M14: Teammates get TEAMMATE_GUIDE.md, not BEHAVIORAL_GUIDE.md."""

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

    def _run_teammate(self, **overrides):
        """Run subagent_start for a teammate agent."""
        data = {
            "session_id": "t",
            "agent_id": "worker-1",
            "agent_type": "backend-worker",
            **overrides,
        }
        return self.subagent_start.run(data, smm_dir=self.smm_dir)

    def test_teammate_gets_teammate_guide_and_values(self):
        """Teammate agent gets TEAMMATE_GUIDE + XP values, not process guide."""
        result = self._run_teammate()
        self.assertIsNotNone(result)
        self.assertIn("Teammate Guide", result)
        self.assertIn("XP Values", result)
        self.assertNotIn("EnterPlanMode", result)

    def test_teammate_guide_has_do_items(self):
        """Teammate guide includes DO items."""
        result = self._run_teammate()
        self.assertIn("TDD", result)
        self.assertIn("small steps", result.lower())
        self.assertIn("file domain", result.lower())
        self.assertIn("message the lead", result.lower())

    def test_teammate_guide_has_dont_items(self):
        """Teammate guide has quality-focused DON'Ts."""
        result = self._run_teammate()
        self.assertIn("code smells", result.lower())
        self.assertIn("500 lines", result)

    def test_teammate_guide_skip_plan_mode(self):
        """Teammate guide skips plan mode."""
        result = self._run_teammate()
        self.assertNotIn("EnterPlanMode", result)

    def test_teammate_guide_has_keep_items(self):
        """Teammate guide has KEEP items for TDD and concerns."""
        result = self._run_teammate()
        self.assertIn("TDD discipline", result)
        self.assertIn("Concern recording", result)

    def test_teammate_guide_has_simplify(self):
        """Teammate guide tells teammates to run /simplify."""
        result = self._run_teammate()
        self.assertIn("/simplify", result)

    def test_teammate_guide_has_event_recording(self):
        """Teammate guide shows how to record events."""
        result = self._run_teammate()
        self.assertIn("append.sh", result)

    def test_teammate_no_sprint_stories_injected(self):
        """Stories come via spawn prompt, not SubagentStart injection."""
        result = self._run_teammate()
        self.assertIsNotNone(result)
        self.assertNotIn("sprint-001", result)
        self.assertNotIn("story-001", result)

    def test_non_teammate_tiers_unaffected(self):
        """Built-in types get XP values (not teammate guide)."""
        for agent_type in ("Plan", "general-purpose"):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "task-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                self.assertIsNotNone(result)
                self.assertNotIn("Teammate Guide", result)
                self.assertIn("XP Values", result)

    def test_teammate_registered_in_coordination(self):
        """Teammate is registered in coordination.json at spawn."""
        import coordination

        self._run_teammate(agent_id="worker-1")
        coord = coordination.read_coordination(self.smm_dir)
        self.assertIn("worker-1", coord)


if __name__ == "__main__":
    unittest.main()
