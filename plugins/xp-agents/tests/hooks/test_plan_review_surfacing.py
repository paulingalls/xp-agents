#!/usr/bin/env python3
"""Plan-review finding-surfacing regression (debt 5e180220db1a).

A teammate-mode xp-plan-reviewer SubagentStop used to return a "/xp-assign"
nudge string. The platform delivers SubagentStop additionalContext to the
SUBAGENT, continuing its turn — so the reviewer took one more turn reacting
to the nudge, and that short reaction BURIED its four-block Final Message
(Concerns / Assumptions / Blocking questions / Next step).

The fix removes the cause: _handle_plan_review_done returns None. The real
teammate gate is the ASSIGN_PENDING marker on disk plus the plan_reviewed
gate event — both still written. These tests pin that contract so the nudge
return can never come back.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
import subagent_stop
from conftest import _HookTestCase, _s, _sprint_json
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_STATUS,
    STATUS_ACTION_PLAN_REVIEWED,
    STATUS_ACTION_SUBAGENT_COMPLETE,
    event_action,
)

_WATERMARK_ID = "test-plan-review-surfacing"


class TestPlanReviewSurfacing(_HookTestCase):
    """run() must NOT return a continuing nudge for the plan reviewer."""

    def _reviewer_input(self, agent_type: str = "xp-plan-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "plan-reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Plan reviewed.",
        }

    def _write_sprint(self, execution_mode=None):
        kw = {} if execution_mode is None else {"execution_mode": execution_mode}
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json([_s("story-001", "narrow gate", "in-progress", **kw)])
        )

    def _statuses(self):
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        return events_of_type(events, EVENT_TYPE_STATUS)

    def test_teammate_path_returns_none(self):
        """Teammate plan-review → run() returns None (was the /xp-assign nudge).

        No continuing additionalContext means the reviewer is not nudged into
        an extra turn, so its four-block Final Message stays terminal.
        """
        self._write_sprint(execution_mode="teammate")
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_teammate_path_keeps_marker_and_gate(self):
        """The real teammate-pipeline gate is intact: ASSIGN_PENDING marker on
        disk AND the plan_reviewed gate event are still written."""
        self._write_sprint(execution_mode="teammate")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)

        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))
        gate_events = [
            e
            for e in self._statuses()
            if event_action(e) == STATUS_ACTION_PLAN_REVIEWED
        ]
        self.assertEqual(len(gate_events), 1)
        self.assertIn("assign_pending", gate_events[0].get("content", ""))

    def test_solo_path_returns_none_and_records_completion(self):
        """Solo (non-teammate) path → returns None + emits completion, no
        marker, no gate event (behavior unchanged)."""
        self._write_sprint(execution_mode="solo")
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)

        self.assertIsNone(result)
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASSIGN_PENDING))
        completions = [
            e
            for e in self._statuses()
            if event_action(e) == STATUS_ACTION_SUBAGENT_COMPLETE
        ]
        self.assertEqual(len(completions), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
