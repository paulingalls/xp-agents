#!/usr/bin/env python3
"""Tests for subagent_stop sprint-reviewer completion handling.

Extracted from test_subagent.py to keep files under the 500-line ceiling.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import subagent_stop
from conftest import (
    _HookTestCase,
    _s,
    _sprint_json,
)

_SPRINT_REVIEW_MIXED = _sprint_json(
    [
        _s("story-001", "Login", "done"),
        _s("story-002", "Register", "done"),
        _s("story-003", "Logout", "deferred"),
        _s("story-004", "Profile", "ready"),
    ],
    sprint_id="sprint-001",
    started="2026-03-15",
    goal="Build auth system",
)


class TestSprintReviewerDone(_HookTestCase):
    """subagent_stop._handle_sprint_review_done runs after xp-sprint-reviewer."""

    def _reviewer_input(self, agent_type: str = "xp-sprint-reviewer") -> dict:
        return {
            "session_id": "t",
            "agent_id": "reviewer-1",
            "agent_type": agent_type,
            "last_assistant_message": "Review complete.",
        }

    def _seed_sprint(self, content: str = _SPRINT_REVIEW_MIXED) -> None:
        (self.smm_dir / "sprint.json").write_text(content)

    def test_returns_none_no_nudge(self):
        """M6: After sprint-reviewer finishes, returns None — sprint retro
        now runs at next session start, not end of session."""
        self._seed_sprint()
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_matches_qualified_agent_type(self):
        """Should match agent_type 'xp-agents:xp-sprint-reviewer' too —
        writes the sprint_end event even if return value is None."""
        self._seed_sprint()
        subagent_stop.run(
            self._reviewer_input(agent_type="xp-agents:xp-sprint-reviewer"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        self.assertEqual(len(sprint_events), 1)

    def test_logs_sprint_end_event(self):
        """Sprint end event has type=sprint, action=end, velocity metadata."""
        self._seed_sprint()
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        self.assertEqual(len(sprint_events), 1)
        meta = sprint_events[0].get("metadata", {})
        self.assertEqual(meta["action"], "end")
        self.assertEqual(meta["sprint_id"], "sprint-001")
        self.assertIn("stories_planned", meta)
        self.assertIn("stories_delivered", meta)
        self.assertIn("stories_carried", meta)

    def test_sprint_end_velocity_values(self):
        """Velocity in sprint end event matches sprint.json data."""
        self._seed_sprint()
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        sprint_events = [e for e in events if e.get("type") == "sprint"]
        meta = sprint_events[0]["metadata"]
        self.assertEqual(meta["stories_planned"], 4)
        self.assertEqual(meta["stories_delivered"], 2)
        self.assertEqual(meta["stories_carried"], 1)

    def test_cleans_up_input_file(self):
        """Removes both legacy and per-invocation review input files."""
        self._seed_sprint()
        legacy = self.smm_dir / ".sprint-review-input.json"
        tempfile_path = self.smm_dir / ".sprint-review-input.abc123"
        legacy.write_text("{}")
        tempfile_path.write_text("{}")
        subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertFalse(legacy.exists())
        self.assertFalse(tempfile_path.exists())

    def test_no_sprint_graceful(self):
        """M6: No sprint.json → still returns None (no nudge), no crash."""
        result = subagent_stop.run(self._reviewer_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
