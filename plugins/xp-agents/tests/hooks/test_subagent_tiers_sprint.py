#!/usr/bin/env python3
"""Tests for SubagentStart sprint-aware tiers and housekeeper handler.

Split from test_subagent_tiers.py -- sprint context and housekeeper tests.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import SAMPLE_SPRINT_MD as _SAMPLE_SPRINT
from conftest import _HookTestCase, make_event, write_smm_fixture

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
        self.assertIn("Extreme Programming", result)
        # Should NOT get SMM content (that comes from preload)
        self.assertNotIn("Ship v1", result)

    def test_retrospective_handler_injects_paths(self):
        """xp-retrospective injects SMM_DIR + RETRO_INPUT."""
        for agent_type in (
            "xp-retrospective",
            "xp-agents:xp-retrospective",
        ):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "retro-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                self.assertIsNotNone(result)
                self.assertIn(f"SMM_DIR={self.smm_dir}", result)
                self.assertIn(
                    f"RETRO_INPUT={self.smm_dir}/.retro-input.json",
                    result,
                )
                self.assertIn("Extreme Programming", result)
                self.assertNotIn("Ship v1", result)

    def test_close_reviewer_has_no_dedicated_handler(self):
        """xp-close-reviewer reads its review fields (mode, source_branch,
        target_branch, diff_command) from the Agent prompt sections the
        close skill embeds — never via SubagentStart injection."""
        for agent_type in (
            "xp-close-reviewer",
            "xp-agents:xp-close-reviewer",
        ):
            with self.subTest(agent_type=agent_type):
                result = self.subagent_start.run(
                    {
                        "session_id": "t",
                        "agent_id": "close-rev-1",
                        "agent_type": agent_type,
                    },
                    smm_dir=self.smm_dir,
                )
                # No special injection — falls through to the default path
                # (XP values only, no REVIEW_INPUT line).
                if result is not None:
                    self.assertNotIn("REVIEW_INPUT=", result)

    def test_sprint_reviewer_gets_values_only(self):
        """xp-sprint-reviewer gets XP values only."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "review-1",
                "agent_type": "xp-sprint-reviewer",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Extreme Programming", result)
        self.assertNotIn("Ship v1", result)

    def test_custom_agent_type_gets_full_smm(self):
        """Custom agent types get full SMM (default tier)."""
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
        """Agent without assigned_stories gets default."""
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
        self.assertIn("Extreme Programming", result)

    def test_code_reviewer_gets_full_smm(self):
        """xp-code-reviewer gets full SMM."""
        for agent_type in (
            "xp-code-reviewer",
            "xp-agents:xp-code-reviewer",
        ):
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
                self.assertIn("Extreme Programming", result)

    def test_other_xp_agents_get_values(self):
        """xp-* agents not in dispatch table get XP values."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "nav-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Extreme Programming", result)

    def test_explore_unchanged(self):
        """Explore still gets Intent + Constraints only."""
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
        """Default (non-xp, non-Explore) gets full SMM."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Risks", result)
        self.assertNotIn("sprint-001", result)


# ===========================================================================
# Housekeeper inline-agent handler tests
# ===========================================================================


class TestSubagentStartHousekeeper(_HookTestCase):
    """xp-housekeeper handler writes curation input and injects paths."""

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

    def _run_housekeeper(self, agent_type: str = "xp-agents:xp-housekeeper") -> str:
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "housekeeper-1",
                "agent_type": agent_type,
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        return result

    def test_writes_curation_input_and_injects_paths(self):
        """Handler writes .curation-input.json and advertises paths."""
        for agent_type in (
            "xp-housekeeper",
            "xp-agents:xp-housekeeper",
        ):
            with self.subTest(agent_type=agent_type):
                curation_file = self.smm_dir / ".curation-input.json"
                curation_file.unlink(missing_ok=True)
                result = self._run_housekeeper(agent_type)
                self.assertTrue(curation_file.exists())
                data = json.loads(curation_file.read_text())
                self.assertIn("current_smm", data)
                self.assertIn("new_since_last_curation", data)
                self.assertIn(f"SMM_DIR={self.smm_dir}", result)
                self.assertIn(f"CURATION_INPUT={curation_file}", result)
                self.assertIn("Extreme Programming", result)

    def test_work_selection_block_when_events_present(self):
        """Session work-selection events produce a block."""
        self._write_events(
            [
                make_event(
                    "decision",
                    topic="retro-try-fix-thing",
                    content="Adopted retro Try: fix the thing",
                ),
                make_event(
                    "status",
                    content=("Deferred retro Try: questions_stop_gate"),
                    metadata={"disposition": "deferred"},
                ),
                make_event("goal", content="Sprint session"),
            ]
        )
        result = self._run_housekeeper()
        self.assertIn("## Session Work Selection", result)
        self.assertIn("fix the thing", result)
        self.assertIn("questions_stop_gate", result)
        self.assertIn("Sprint session", result)

    def test_no_work_selection_block_when_absent(self):
        """Without work-selection events, no block is emitted."""
        self._write_events(
            [
                make_event("customer_input", content="unrelated event"),
                make_event("concern", content="unrelated concern"),
            ]
        )
        result = self._run_housekeeper()
        self.assertNotIn("## Session Work Selection", result)

    def test_session_boundary_filters_old_events(self):
        """retro-try-* decisions before session_end are ignored."""
        self._write_events(
            [
                make_event(
                    "decision",
                    topic="retro-try-old-item",
                    content=("Adopted retro Try: old item from prior session"),
                ),
                make_event(
                    "session_end",
                    content="prior session ended",
                ),
            ]
        )
        result = self._run_housekeeper()
        self.assertNotIn("## Session Work Selection", result)
        self.assertNotIn("old item from prior session", result)


if __name__ == "__main__":
    unittest.main()
