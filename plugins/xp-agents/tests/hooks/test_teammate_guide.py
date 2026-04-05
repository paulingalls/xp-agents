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

from conftest import _HookTestCase

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

    def _run_teammate(self, **overrides):
        """Run subagent_start for a teammate agent."""
        data = {
            "session_id": "t",
            "agent_id": "worker-1",
            "agent_type": "backend-worker",
            **overrides,
        }
        return self.subagent_start.run(data, smm_dir=self.smm_dir)

    def test_teammate_gets_teammate_guide_not_solo(self):
        """Teammate agent gets TEAMMATE_GUIDE, not BEHAVIORAL_GUIDE."""
        result = self._run_teammate()
        self.assertIsNotNone(result)
        self.assertIn("Teammate Guide", result)
        self.assertNotIn("XP Agent Behavioral Guide", result)

    def test_teammate_guide_has_do_items(self):
        """Teammate guide includes DO items from design doc."""
        result = self._run_teammate()
        self.assertIn("TDD", result)
        self.assertIn("commit", result.lower())
        self.assertIn("file domain", result.lower())
        self.assertIn("message the lead", result.lower())
        self.assertIn("record", result.lower())  # record decisions/assumptions

    def test_teammate_guide_has_dont_items(self):
        """Teammate guide excludes lead-only skill references."""
        result = self._run_teammate()
        self.assertNotIn("/xp-kickoff", result)
        self.assertNotIn("/xp-housekeeping", result)
        self.assertNotIn("/xp-goal-collection", result)
        self.assertNotIn("/xp-run-retrospective", result)

    def test_teammate_guide_skip_plan_mode(self):
        """Teammate guide does not reference EnterPlanMode."""
        result = self._run_teammate()
        self.assertNotIn("EnterPlanMode", result)

    def test_teammate_no_sprint_stories_injected(self):
        """Stories come via spawn prompt, not SubagentStart injection."""
        result = self._run_teammate()
        self.assertIsNotNone(result)
        # Sprint content should NOT appear — stories come from spawn prompt
        self.assertNotIn("sprint-001", result)
        self.assertNotIn("story-001", result)

    def test_non_teammate_tiers_unaffected(self):
        """Built-in types still get solo behavioral guide."""
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
                self.assertIn("XP Agent Behavioral Guide", result)

    def test_review_cycle_referenced(self):
        """Teammate guide references commit-gated review cycle."""
        result = self._run_teammate()
        self.assertIn("review", result.lower())
        self.assertIn("/simplify", result.lower())

    def test_teammate_registered_in_coordination(self):
        """Teammate is registered in coordination.json at spawn."""
        import coordination

        self._run_teammate(agent_id="worker-1")
        coord = coordination.read_coordination(self.smm_dir)
        self.assertIn("worker-1", coord)


if __name__ == "__main__":
    unittest.main()
