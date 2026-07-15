#!/usr/bin/env python3
"""Tests for question_answered.py (PostToolUse/PostToolUseFailure:AskUserQuestion)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_ANSWER, EVENT_TYPE_CUSTOMER_INPUT


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

    def _make_failure_input(self, error="The user wants to clarify."):
        return {
            "session_id": "test-session",
            "tool_name": "AskUserQuestion",
            "tool_input": {"question": "Should we use approach A?"},
            "error": error,
            "agent_id": "main",
        }

    # --- Success path (PostToolUse) ---

    def test_clears_gate_and_records_answer(self):
        """With .question-gate, should clear it and append answer event."""
        gate = self.smm_dir / ".question-gate"
        gate.write_text("original-question-id")

        import question_answered

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        self.assertFalse(gate.exists())
        events = self._read_events()
        answers = events_of_type(events, EVENT_TYPE_ANSWER)
        self.assertEqual(len(answers), 1)
        self.assertIn("original-question-id", answers[0].get("references", []))

    def test_gate_success_no_customer_input(self):
        """With gate, answer event is written — no duplicate customer_input."""
        gate = self.smm_dir / ".question-gate"
        gate.write_text("q-id")

        import question_answered

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        inputs = events_of_type(self._read_events(), EVENT_TYPE_CUSTOMER_INPUT)
        self.assertEqual(len(inputs), 0)

    def test_no_gate_logs_customer_input(self):
        """Without gate, answers captured as customer_input."""
        import question_answered

        question_answered.run(
            self._make_ask_input("User chose option B"),
            smm_dir=self.smm_dir,
        )

        events = self._read_events()
        answers = events_of_type(events, EVENT_TYPE_ANSWER)
        self.assertEqual(len(answers), 0)
        inputs = events_of_type(events, EVENT_TYPE_CUSTOMER_INPUT)
        self.assertEqual(len(inputs), 1)
        self.assertIn("option B", inputs[0]["content"])

    def test_success_does_not_set_asking_user_marker(self):
        """Successful answer — agent got what it needed, no deferral."""
        import markers
        import question_answered

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASKING_USER))

    def test_success_with_gate_does_not_set_asking_user_marker(self):
        """Blocking-question success — gate cleared, no deferral marker."""
        import markers
        import question_answered

        gate = self.smm_dir / ".question-gate"
        gate.write_text("original-question-id")

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        self.assertFalse(gate.exists())
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASKING_USER))

    def test_two_open_blocking_questions_both_resolve(self):
        """Two 🔴 questions before an answer: the second clobbers QUESTION_GATE,
        but BOTH must resolve — not just the last one recorded in the gate."""
        import _common
        import question_answered
        import resolution

        q1 = _common.make_event(
            _common.QUESTION, "main", "First blocker?", priority="\U0001f534"
        )
        _common.append_safe(self.smm_dir, q1)
        q2 = _common.make_event(
            _common.QUESTION, "main", "Second blocker?", priority="\U0001f534"
        )
        _common.append_safe(self.smm_dir, q2)

        gate = self.smm_dir / ".question-gate"
        gate.write_text(q2["id"])

        question_answered.run(self._make_ask_input(), smm_dir=self.smm_dir)

        events = self._read_events()
        resolutions = resolution.compute_resolutions(events)
        answered = resolution.collect_all_resolved_ids(resolutions)
        self.assertIn(q1["id"], answered)
        self.assertIn(q2["id"], answered)

    def test_no_open_blocking_questions_logs_customer_input(self):
        """No 🔴 question / no gate: unchanged customer_input behavior."""
        import question_answered

        question_answered.run(
            self._make_ask_input("User chose option B"),
            smm_dir=self.smm_dir,
        )

        events = self._read_events()
        answers = events_of_type(events, EVENT_TYPE_ANSWER)
        self.assertEqual(len(answers), 0)
        inputs = events_of_type(events, EVENT_TYPE_CUSTOMER_INPUT)
        self.assertEqual(len(inputs), 1)

    def test_xp_agent_skips(self):
        """xp-agent calls must not write markers or events."""
        import markers
        import question_answered

        xp_input = self._make_ask_input()
        xp_input["agent_type"] = "xp-plan-reviewer"

        question_answered.run(xp_input, smm_dir=self.smm_dir)

        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ASKING_USER))
        self.assertEqual(len(self._read_events()), 0)

    # --- Failure path (PostToolUseFailure: "Chat about this...") ---

    def test_failure_sets_asking_user_marker(self):
        """Chat about this... sets marker so stop gate defers."""
        import markers
        import question_answered

        question_answered.run(self._make_failure_input(), smm_dir=self.smm_dir)

        self.assertTrue(markers.marker_exists(self.smm_dir, markers.ASKING_USER))

    def test_failure_logs_customer_input(self):
        """Failure logs customer_input with partial answers."""
        import question_answered

        error_text = "Answer: Blue\nAnswer: Spring\n(No answer provided)"
        question_answered.run(
            self._make_failure_input(error_text),
            smm_dir=self.smm_dir,
        )

        inputs = events_of_type(self._read_events(), EVENT_TYPE_CUSTOMER_INPUT)
        self.assertEqual(len(inputs), 1)
        self.assertIn("Blue", inputs[0]["content"])

    def test_failure_does_not_clear_question_gate(self):
        """Failure path leaves question gate intact."""
        import question_answered

        gate = self.smm_dir / ".question-gate"
        gate.write_text("original-question-id")

        question_answered.run(self._make_failure_input(), smm_dir=self.smm_dir)

        self.assertTrue(gate.exists())

    def test_failure_does_not_record_answer_event(self):
        """Failure path does not record answer events."""
        import question_answered

        gate = self.smm_dir / ".question-gate"
        gate.write_text("original-question-id")

        question_answered.run(self._make_failure_input(), smm_dir=self.smm_dir)

        answers = events_of_type(self._read_events(), EVENT_TYPE_ANSWER)
        self.assertEqual(len(answers), 0)

    def _read_events(self):
        events_file = self.smm_dir / "events.jsonl"
        text = events_file.read_text().strip()
        if not text:
            return []
        return [json.loads(line) for line in text.split("\n") if line.strip()]


if __name__ == "__main__":
    unittest.main()
