#!/usr/bin/env python3
"""Tests for question_answered.py (PostToolUse:AskUserQuestion hook)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase


class TestQuestionAnswered(_HookTestCase):
    """PostToolUse:AskUserQuestion clears gate and records answer."""

    def _make_ask_input(self, tool_response="The user said yes"):
        return {
            "session_id": "test-session",
            "tool_name": "AskUserQuestion",
            "tool_input": {"question": "Should we use approach A?"},
            "tool_response": tool_response,
            "agent_id": "main",
        }

    def test_clears_gate_and_records_answer(self):
        """With .question-gate, should clear it and append answer event."""
        gate = self.smm_dir / ".question-gate"
        gate.write_text("original-question-id")

        import question_answered

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        self.assertFalse(gate.exists())
        events = self._read_events()
        answers = [e for e in events if e.get("type") == "answer"]
        self.assertEqual(len(answers), 1)
        self.assertIn("original-question-id", answers[0].get("references", []))

    def test_no_gate_no_action(self):
        """Without .question-gate, should exit cleanly with no events."""
        import question_answered

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        events = self._read_events()
        answers = [e for e in events if e.get("type") == "answer"]
        self.assertEqual(len(answers), 0)

    def _read_events(self):
        events_file = self.smm_dir / "events.jsonl"
        text = events_file.read_text().strip()
        if not text:
            return []
        return [json.loads(line) for line in text.split("\n") if line.strip()]


if __name__ == "__main__":
    unittest.main()
