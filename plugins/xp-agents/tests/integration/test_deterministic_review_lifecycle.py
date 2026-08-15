#!/usr/bin/env python3
"""End-to-end test for the deterministic event emission doctrine (sprint-041).

Verifies the producer (review_cycle_done.py) → event log → consumer
(retro_metrics) chain: simulating PostToolUse:Skill / PostToolUse:Agent
inputs results in canonical metadata.action events that retro_metrics
counts via _ACTION_TO_COUNTER without touching content regex.

Closes the meta-irony loop the doctrine identifies: a session running
QR / security-review / simplify can now count its own runs in the next
retrospective.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_metrics
from conftest import _IntegrationTestCase, _make_agent_input, _make_skill_input
from event_schema import (
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    event_action,
)


class TestDeterministicReviewLifecycle(_IntegrationTestCase):
    """Producer → event → consumer chain for the doctrine's lifecycle moments."""

    def _trigger_skill(self, skill: str) -> tuple[list[dict], dict]:
        """Run review_cycle_done.py for *skill* and return (events, counts)."""
        result = self._run_script(
            "review_cycle_done.py", _make_skill_input(skill, cwd=str(self.tmpdir))
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        events = self._read_events()
        return events, retro_metrics._classify_lifecycle_events(events)

    def _trigger_agent(self, subagent_type: str) -> tuple[list[dict], dict]:
        """Run review_cycle_done.py for an Agent completion."""
        result = self._run_script(
            "review_cycle_done.py",
            _make_agent_input(subagent_type, agent_type="", cwd=str(self.tmpdir)),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        events = self._read_events()
        return events, retro_metrics._classify_lifecycle_events(events)

    @staticmethod
    def _action_count(events: list[dict], action: str) -> int:
        return sum(1 for e in events if event_action(e) == action)

    def test_reviewer_completion_increments_quality_reviews_counter(self):
        """The quality counter is fed by the REVIEWER returning, not by the
        skill launching — the inline skill's own hook fires before it reviews."""
        events, counts = self._trigger_agent("xp-agents:xp-code-reviewer")
        self.assertEqual(self._action_count(events, STATUS_ACTION_QR_COMPLETE), 1)
        self.assertGreaterEqual(counts["quality_reviews"], 1)

    def test_qr_skill_launch_increments_nothing(self):
        """Non-vacuity for the leg above: invoking the skill must not count as
        a review having happened."""
        events, counts = self._trigger_skill("xp-quality-review")
        self.assertEqual(self._action_count(events, STATUS_ACTION_QR_COMPLETE), 0)
        self.assertEqual(counts["quality_reviews"], 0)

    def test_security_review_completion_increments_security_checks_counter(self):
        events, counts = self._trigger_skill("security-review")
        self.assertEqual(self._action_count(events, STATUS_ACTION_SECURITY_COMPLETE), 1)
        self.assertGreaterEqual(counts["security_checks"], 1)

    def test_code_review_completion_increments_simplifies_counter(self):
        events, counts = self._trigger_skill("code-review")
        self.assertEqual(self._action_count(events, STATUS_ACTION_SIMPLIFY_COMPLETE), 1)
        self.assertGreaterEqual(counts["simplifies"], 1)

    def test_full_review_cycle_increments_all_three_counters(self):
        """Doctrine's primary acceptance — a session that ran the full
        review cycle has non-zero counters across code-review, QR, and security."""
        for skill in ("code-review", "security-review"):
            result = self._run_script(
                "review_cycle_done.py", _make_skill_input(skill, cwd=str(self.tmpdir))
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
        self._trigger_agent("xp-agents:xp-code-reviewer")
        counts = retro_metrics._classify_lifecycle_events(self._read_events())
        self.assertGreaterEqual(counts["simplifies"], 1)
        self.assertGreaterEqual(counts["quality_reviews"], 1)
        self.assertGreaterEqual(counts["security_checks"], 1)


if __name__ == "__main__":
    unittest.main()
