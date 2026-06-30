#!/usr/bin/env python3
"""Tests for SubagentStart tiered context injection.

Split from test_subagent.py to stay under 500-line cap.
Covers: tiered SMM injection, pillar filtering.
Sprint-aware tiers live in test_subagent_tiers_sprint.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_event, write_smm_fixture
from event_schema import EVENT_TYPE_STATUS

# ===========================================================================
# subagent_start.py core tests (moved from test_subagent.py)
# ===========================================================================


class TestSubagentStart(_HookTestCase):
    def test_xp_agent_gets_values_only(self):
        import subagent_start

        result = subagent_start.run(
            {
                "session_id": "test",
                "agent_id": "exp-1",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_missing_smm_dir_still_gets_values(self):
        import subagent_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "exp-1"},
            smm_dir=fake_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_returns_values_without_smm_file(self):
        """Without curated SMM file, non-Explore agent gets values."""
        import subagent_start

        self._write_events([make_event()])
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_reads_curated_smm_from_disk(self):
        """M5: SubagentStart reads curated SMM from disk."""
        import subagent_start

        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Ship v1", result)

    def test_empty_events_still_gets_values(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Extreme Programming", result)

    def test_default_agent_id(self):
        """Default agent_id is 'subagent'."""
        import subagent_start

        self._write_events([make_event()])
        subagent_start.run(
            {"session_id": "test"},
            smm_dir=self.smm_dir,
        )
        events = self._read_events()
        start_events = [
            e for e in events if "Subagent subagent started" in e.get("content", "")
        ]
        self.assertEqual(len(start_events), 1)


class TestSubagentStartEvent(_HookTestCase):
    """Tests for SubagentStart event recording."""

    def test_start_records_status_event(self):
        import subagent_start

        self._write_events([make_event()])
        subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        events = self._read_events()
        self.assertEqual(len(events), 2)
        start_ev = events[1]
        self.assertEqual(start_ev["type"], EVENT_TYPE_STATUS)
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
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["agent_id"], "xp-nav-1")


# ===========================================================================
# SubagentStart tiered injection tests
# ===========================================================================


class TestSubagentStartTieredInjection(_HookTestCase):
    """SubagentStart injects tiered context based on agent type."""

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
        assert result is not None
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
        assert result is not None
        self.assertNotIn("BEHAVIORAL_GUIDE", result)

    def test_unknown_agent_type_gets_full_smm_and_values(self):
        """An unspecified/unknown agent type gets full SMM + XP values — the
        safe default. (The named 'general-purpose' type is the reference tier;
        see TestGenericReferenceTier.)"""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertIn("Risks", result)
        self.assertIn("Wisdom", result)
        self.assertIn("Extreme Programming", result)
        self.assertNotIn("EnterPlanMode", result)

    def test_plan_agent_gets_full_smm_and_values(self):
        """Plan agent gets full SMM + XP values."""
        result = self.subagent_start.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
            },
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Intent", result)
        self.assertIn("Extreme Programming", result)
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
        assert result is not None
        self.assertIn("<smm-context>", result)
        self.assertIn("</smm-context>", result)


# ===========================================================================
# Sequential-discipline note (sprint-098 story-001) — every tier EXCEPT the
# generic catch-alls (workflow-subagent / general-purpose / claude; see
# TestGenericReferenceTier)
# ===========================================================================


class TestSubagentSequentialNote(_HookTestCase):
    """The sequential-discipline note injects into every subagent tier except the
    generic catch-alls (workflow-subagent / general-purpose / claude), which do
    independent reads — the case the note already exempts."""

    _SIGNATURE = "single-purpose sequential agent"
    _EXEMPTION = "only to independent reads"

    def test_default_agent_gets_sequential_note(self):
        """A default (Task) agent's context carries the sequential note."""
        import subagent_start

        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        result = subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn(self._SIGNATURE, result)

    def test_xp_agent_gets_sequential_note(self):
        """An xp-* values-only-tier agent still carries the note."""
        import subagent_start

        result = subagent_start.run(
            {"session_id": "t", "agent_id": "xp-1", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn(self._SIGNATURE, result)

    def test_missing_smm_dir_gets_sequential_note(self):
        """The smm_dir-None early-return path also carries the note."""
        import subagent_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = subagent_start.run(
            {"session_id": "t", "agent_id": "x-1"},
            smm_dir=fake_dir,
        )
        assert result is not None
        self.assertIn(self._SIGNATURE, result)

    def test_sequential_note_exempts_independent_reads(self):
        """The note preserves legitimate independent-read batching."""
        import subagent_start

        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        result = subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn(self._EXEMPTION, result)


class TestGenericReferenceTier(_HookTestCase):
    """Generic catch-alls (workflow-subagent / general-purpose / claude) are
    purpose-blind and prompt-driven: inject XP values + a cheap SMM reference
    pointer — no full render, no sequential note. A code-writing one renders the
    curated SMM on demand from the pointer; a review/research one skips it."""

    _GENERIC_TYPES = ("workflow-subagent", "general-purpose", "claude")

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

    def _run(self, agent_type):
        return self.subagent_start.run(
            {"session_id": "t", "agent_id": "g-1", "agent_type": agent_type},
            smm_dir=self.smm_dir,
        )

    def test_gets_values_and_reference_not_full_smm(self):
        for agent_type in self._GENERIC_TYPES:
            with self.subTest(agent_type=agent_type):
                result = self._run(agent_type)
                assert result is not None
                # XP values — every agent should know XP.
                self.assertIn("Extreme Programming", result)
                # Reference pointer: SMM_DIR + render command + the gate phrase.
                self.assertIn(f"SMM_DIR={self.smm_dir}", result)
                self.assertIn("writes, designs, or changes code", result)
                self.assertIn("smm_cli.py", result)
                self.assertIn("render", result)
                # NOT the full render: neither the wrapper nor the pillar values.
                for token in (
                    "<smm-context>",
                    "Ship v1",
                    "Python 3.10+",
                    "Auth module fragile",
                    "TDD always",
                ):
                    self.assertNotIn(token, result)

    def test_no_sequential_note(self):
        for agent_type in self._GENERIC_TYPES:
            with self.subTest(agent_type=agent_type):
                result = self._run(agent_type)
                assert result is not None
                self.assertNotIn("single-purpose sequential agent", result)


if __name__ == "__main__":
    unittest.main()
