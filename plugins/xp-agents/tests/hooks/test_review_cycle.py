#!/usr/bin/env python3
"""Tests for review cycle hooks: review_cycle_done and subagent review flags.

Split from test_subagent.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import review_cycle_done
import security
import subagent_stop
from conftest import _HookTestCase


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

    def test_triage_does_not_record_review_complete(self):
        """Triage-only should not claim a full review happened."""
        review_cycle_done.run(
            self._skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        events = _common.read_events_raw(self.smm_dir)
        review_events = [
            e for e in events if "Security review complete" in e.get("content", "")
        ]
        self.assertEqual(len(review_events), 0)

    def test_security_review_records_review_complete(self):
        """/security-review should record the review complete event."""
        review_cycle_done.run(
            self._skill_input("security-review"), smm_dir=self.smm_dir
        )
        events = _common.read_events_raw(self.smm_dir)
        review_events = [
            e for e in events if "Security review complete" in e.get("content", "")
        ]
        self.assertEqual(len(review_events), 1)
        self.assertEqual(review_events[0]["agent_id"], "security-review")

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

    def test_simplify_nudges_quality_review(self):
        """After /simplify, nudge to run /xp-quality-review."""
        result = review_cycle_done.run(
            self._skill_input("simplify"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_quality_review_nudges_security_triage(self):
        """After /xp-quality-review, nudge to run /xp-security-triage."""
        result = review_cycle_done.run(
            self._skill_input("xp-quality-review"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("/xp-security-triage", result)

    def test_security_triage_nudges_commit(self):
        """After /xp-security-triage, nudge to commit."""
        result = review_cycle_done.run(
            self._skill_input("xp-security-triage"), smm_dir=self.smm_dir
        )
        self.assertIsNotNone(result)
        self.assertIn("commit", result.lower())


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
