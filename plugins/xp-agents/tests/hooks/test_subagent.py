#!/usr/bin/env python3
"""Tests for subagent hooks and user prompt logging.

Split from the monolithic test_hooks.py.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import subagent_stop
import user_prompt_log
from conftest import _HookTestCase, make_event

# ===========================================================================
# subagent_start.py tests
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

    def test_returns_guide_without_smm_file(self):
        """Without curated SMM file, non-Explore agent still gets behavioral guide."""
        import subagent_start

        self._write_events([make_event()])
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        # Non-Explore agent gets behavioral guide even without SMM
        self.assertIsNotNone(result)
        self.assertIn("Behavioral Guide", result)

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

    def test_empty_events_still_gets_guide(self):
        import subagent_start

        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        # Non-Explore agent gets behavioral guide even with empty events
        self.assertIsNotNone(result)
        self.assertIn("Behavioral Guide", result)

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

    def test_falls_back_to_guide_without_smm_file(self):
        """Without curated SMM, non-Explore agent gets behavioral guide."""
        import subagent_start

        self._write_events([make_event("goal", content="Ship v1")])
        # No SHARED_MENTAL_MODEL.md on disk
        result = subagent_start.run(
            {"session_id": "test", "agent_id": "explorer-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Behavioral Guide", result)


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
            {"session_id": "test", "agent_id": "xp-nav-1", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        events = self._read_events()
        # xp- agents should not write start events
        self.assertEqual(len(events), 1)


# ===========================================================================
# SubagentStart tiered injection tests
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
        """Explore agent gets Intent + Constraints only, not Risks or Wisdom."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "explore-1", "agent_type": "Explore"},
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
            {"session_id": "t", "agent_id": "explore-1", "agent_type": "Explore"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        # Behavioral guide contains "Honesty Principle" or "Courage"
        # The key point: Explore should NOT include the guide
        self.assertNotIn("BEHAVIORAL_GUIDE", result)

    def test_general_agent_gets_full_smm_and_guide(self):
        """General-purpose agent gets full SMM + behavioral guide."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertIn("Risks", result)
        self.assertIn("Wisdom", result)

    def test_plan_agent_gets_full_smm_and_guide(self):
        """Plan agent gets full SMM + behavioral guide."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "plan-1", "agent_type": "Plan"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Intent", result)
        self.assertIn("Constraints", result)
        self.assertIn("Risks", result)
        self.assertIn("Wisdom", result)

    def test_explore_wraps_in_smm_context(self):
        """Explore injection is wrapped in <smm-context> tags."""
        result = self.subagent_start.run(
            {"session_id": "t", "agent_id": "explore-1", "agent_type": "Explore"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("<smm-context>", result)
        self.assertIn("</smm-context>", result)


# ===========================================================================
# user_prompt_log.py tests — Milestone 3.4
# ===========================================================================


class TestUserPromptLog(_HookTestCase):
    def test_logs_prompt_as_customer_input(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hello world"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "Hello world")

    def test_agent_id_is_customer(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_xp_agent_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi", "agent_type": "xp-housekeeping"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Should not crash
        user_prompt_log.run(
            {"session_id": "t", "prompt": "Hi"},
            smm_dir=fake_dir,
        )

    def test_empty_prompt_skips(self):
        user_prompt_log.run(
            {"session_id": "t", "prompt": ""},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_task_notification_skips(self):
        user_prompt_log.run(
            {
                "session_id": "t",
                "prompt": "<task-notification>\n<task-id>abc123</task-id>\n",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_long_prompt_truncated(self):
        long_prompt = "x" * 15000
        user_prompt_log.run(
            {"session_id": "t", "prompt": long_prompt},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_goals_present_no_block(self):
        """With goals recorded, prompt proceeds normally."""
        self._write_events([make_event("goal", content="Ship MVP")])
        result = user_prompt_log.run(
            {"session_id": "t", "prompt": "do something"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# subagent_stop.py tests — Milestone 3.4
# ===========================================================================


class TestSubagentStop(_HookTestCase):
    def test_records_minimal_status(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("task-1", statuses[0]["content"])
        self.assertEqual(statuses[0]["working_on"], [])

    def test_xp_agent_skips(self):
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-housekeeping",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=fake_dir,
        )

    def test_default_agent_id(self):
        subagent_stop.run(
            {"session_id": "t", "last_assistant_message": "Done"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("subagent", statuses[0]["content"])

    def test_missing_last_message(self):
        subagent_stop.run(
            {"session_id": "t", "agent_id": "task-1"},
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_conflict_detection_runs(self):
        # Set up a contradiction in the log
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._write_events([a, d])

        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_no_false_positive_conflicts(self):
        # Clean log with no conflicts
        self._write_events(
            [make_event("status", agent_id="main", working_on=["src/a.ts"])]
        )
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)


class TestSubagentStopPlanGate(_HookTestCase):
    """SubagentStop writes plan gate for Plan subagents (Agent tool flow)."""

    def test_plan_writes_awaiting_review_marker(self):
        """Plan subagent should write marker file and gate event."""
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Write tests\n2. Implement",
            },
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertTrue(marker.exists())
        events = _common.read_events_raw(self.smm_dir)
        gate_events = [
            e for e in events if "plan_awaiting_review" in e.get("content", "")
        ]
        self.assertEqual(len(gate_events), 1)

    def test_plan_records_completion_and_gate(self):
        """Both completion status and gate marker should be written."""
        subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Do stuff",
            },
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 2)  # completion + gate


class TestSubagentStopNoReviewerNudge(_HookTestCase):
    """subagent_stop.py no longer nudges xp-subagent-reviewer (removed)."""

    def test_regular_subagent_returns_none(self):
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_returns_none(self):
        result = subagent_stop.run(
            {
                "session_id": "t",
                "agent_id": "task-1",
                "agent_type": "xp-housekeeping",
                "last_assistant_message": "Done",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


import markers  # noqa: E402
import review_cycle_done  # noqa: E402
import security  # noqa: E402


class TestReviewCycleDone(_HookTestCase):
    """PostToolUse:Skill hook sets review cycle flags after review skills."""

    def _skill_input(self, skill: str = "security-review", **overrides) -> dict:
        data = {
            "session_id": "t",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
            "agent_id": "main",
        }
        data.update(overrides)
        return data

    def test_security_review_sets_flag_and_marker(self):
        review_cycle_done.run(self._skill_input(), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["security_review_done"])
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_simplify_sets_flag(self):
        review_cycle_done.run(self._skill_input("simplify"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])
        # Simplify should NOT write security marker
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_quality_review_sets_flag(self):
        review_cycle_done.run(
            self._skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_security_triage_sets_flag(self):
        review_cycle_done.run(
            self._skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["security_review_done"])
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_qualified_simplify_name(self):
        """Plugin-qualified skill names also match."""
        review_cycle_done.run(
            self._skill_input("xp-agents:simplify"), smm_dir=self.smm_dir
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_ignores_other_skills(self):
        review_cycle_done.run(self._skill_input("xp-kickoff"), smm_dir=self.smm_dir)
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])
        self.assertFalse(cycle["security_review_done"])

    def test_xp_agent_skips(self):
        result = review_cycle_done.run(
            self._skill_input(agent_type="xp-test"), smm_dir=self.smm_dir
        )
        self.assertIsNone(result)


class TestSubagentStopReviewFlags(_HookTestCase):
    """SubagentStop backup: detect review-related subagent completions."""

    def _stop_input(self, agent_id: str, agent_type: str = "", **overrides) -> dict:
        data = {
            "session_id": "t",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "last_assistant_message": "Done",
        }
        data.update(overrides)
        return data

    def test_simplify_agent_type_sets_flag(self):
        """SubagentStop with agent_type containing 'simplify' sets flag."""
        subagent_stop.run(
            self._stop_input("task-1", agent_type="simplify"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_quality_review_agent_type_sets_flag(self):
        """SubagentStop with agent_type 'xp-quality-review' sets flag."""
        subagent_stop.run(
            self._stop_input("task-2", agent_type="xp-quality-review"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["quality_review_done"])

    def test_simplify_agent_id_sets_flag(self):
        """SubagentStop with agent_id containing 'simplify' sets flag."""
        subagent_stop.run(
            self._stop_input("simplify-reuse-1", agent_type=""),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_regular_subagent_no_flag(self):
        """Regular subagent does not set any review flags."""
        subagent_stop.run(
            self._stop_input("task-3", agent_type="task"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])

    def test_plan_subagent_no_review_flag(self):
        """Plan subagent writes plan marker but not review flags."""
        subagent_stop.run(
            self._stop_input("plan-1", agent_type="Plan"),
            smm_dir=self.smm_dir,
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertFalse(cycle["simplify_done"])
        self.assertFalse(cycle["quality_review_done"])


if __name__ == "__main__":
    unittest.main()
