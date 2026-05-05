#!/usr/bin/env python3
"""Tests for open-questions nudge dedup cache in pre_tool_bash.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import pre_tool_bash
from conftest import _HookTestCase, _make_bash_input, make_event
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_QUESTION

_APPEND = "bash /plugin/smm/append.sh"


def _decision_cmd() -> str:
    return f"{_APPEND} --type {EVENT_TYPE_DECISION} --topic foo --content bar"


class TestNudgeDedupCache(_HookTestCase):
    """Per-(question_id, agent_id) fire counter mutes after N=2."""

    def _run_decision(self, agent_id: str = "main") -> str | None:
        return pre_tool_bash.run(
            _make_bash_input(command=_decision_cmd(), agent_id=agent_id),
            smm_dir=self.smm_dir,
        )

    def _setup_open_question(self, qid: str = "aaaaaaaaaaaa") -> None:
        self._write_events(
            [
                make_event(
                    EVENT_TYPE_QUESTION,
                    id=qid,
                    topic="auth",
                    content="Should refresh tokens rotate on every request?",
                )
            ]
        )

    def test_first_two_fires_include_question(self):
        """First 2 decision appends each produce nudge with the open question."""
        self._setup_open_question()

        result1 = self._run_decision()
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertIn("aaaaaaaaaaaa", result1)

        result2 = self._run_decision()
        self.assertIsNotNone(result2)
        assert result2 is not None
        self.assertIn("aaaaaaaaaaaa", result2)

    def test_third_fire_mutes_question(self):
        """3rd decision append omits the muted question from nudge."""
        self._setup_open_question()

        self._run_decision()
        self._run_decision()
        result3 = self._run_decision()

        self.assertIsNone(result3)

    def test_independent_agent_ids(self):
        """Different agent_ids maintain independent fire counts."""
        self._setup_open_question()

        self._run_decision(agent_id="agent-a")
        self._run_decision(agent_id="agent-a")

        result_b = self._run_decision(agent_id="agent-b")
        self.assertIsNotNone(result_b)
        assert result_b is not None
        self.assertIn("aaaaaaaaaaaa", result_b)

        result_a = self._run_decision(agent_id="agent-a")
        self.assertIsNone(result_a)

    def test_cleanup_removes_marker(self):
        """cleanup_agent_markers deletes the QUESTION_NUDGED marker."""
        self._setup_open_question()
        self._run_decision()

        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.QUESTION_NUDGED, "main")
        )

        markers.cleanup_agent_markers(self.smm_dir, "main")

        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.QUESTION_NUDGED, "main")
        )

    def test_resolved_question_not_nudged(self):
        """Question resolved between fires doesn't appear in nudge."""
        q = make_event(
            EVENT_TYPE_QUESTION,
            id="aaaaaaaaaaaa",
            topic="auth",
            content="Should refresh tokens rotate?",
        )
        d = make_event(
            EVENT_TYPE_DECISION,
            id="cccccccccccc",
            topic="auth",
            content="Yes, rotate on every request",
            metadata={"resolves": ["aaaaaaaaaaaa"]},
        )
        self._write_events([q, d])

        result = self._run_decision()
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
