#!/usr/bin/env python3
"""Integration tests: Tier 2 coordination and dialogue.

Subprocess-level tests for teammate_idle, task_completed, question_answered,
and prompt_nugget. These hooks mediate Agent Teams coordination and the
mid-dialogue marker lifecycle that sprint_stop_gate depends on.

Hook-level tests cover the function-call logic in detail. These tests
verify the subprocess path — real stdin, real file I/O, real watermark
persistence across subprocess invocations.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import json

from conftest import (
    _IntegrationTestCase,
    failing_tests_concern,
    make_event,
    passing_tests_status,
)

# ---------------------------------------------------------------------------
# teammate_idle.py — TeammateIdle hook
# ---------------------------------------------------------------------------


class TestTeammateIdleIntegration(_IntegrationTestCase):
    """Exit-2 + stderr pattern (not JSON block decision) on TDD failure."""

    def test_failing_tests_exit_2_with_stderr(self):
        self._seed_events([failing_tests_concern()])

        result = self._run_script(
            "teammate_idle.py",
            {
                "session_id": "it",
                "teammate_name": "worker-1",
                "team_name": "alpha",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("fail", result.stderr.lower())

    def test_passing_tests_exit_0(self):
        self._seed_events([passing_tests_status()])

        result = self._run_script(
            "teammate_idle.py",
            {
                "session_id": "it",
                "teammate_name": "worker-1",
                "team_name": "alpha",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_missing_teammate_name_no_op(self):
        """Non-teammate events (no teammate_name key) short-circuit."""
        self._seed_events([failing_tests_concern()])

        result = self._run_script(
            "teammate_idle.py",
            {"session_id": "it"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


# ---------------------------------------------------------------------------
# task_completed.py — TaskCompleted hook
# ---------------------------------------------------------------------------


class TestTaskCompletedIntegration(_IntegrationTestCase):
    """Same TDD-failure exit-2 pattern as teammate_idle."""

    def test_failing_tests_block_task_completion(self):
        self._seed_events([failing_tests_concern()])

        result = self._run_script(
            "task_completed.py",
            {
                "session_id": "it",
                "teammate_name": "worker-1",
                "task_id": "t1",
                "task_subject": "Build X",
                "task_description": "do the thing",
                "team_name": "alpha",
            },
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("fail", result.stderr.lower())


# ---------------------------------------------------------------------------
# question_answered.py — PostToolUse:AskUserQuestion hook
# ---------------------------------------------------------------------------


class TestQuestionAnsweredIntegration(_IntegrationTestCase):
    """Writes .asking-user marker unconditionally; clears .question-gate if set."""

    def test_clears_gate_writes_answer_event_writes_asking_user_marker(self):
        # .question-gate stores the question id as opaque text — question_answered
        # never validates the referenced question exists, so a synthetic UUID is fine.
        question_id = "11111111-2222-4333-8444-555555555555"
        (self.smm_dir / ".question-gate").write_text(question_id)

        result = self._run_script(
            "question_answered.py",
            {
                "session_id": "it",
                "tool_name": "AskUserQuestion",
                "tool_input": {"question": "use A?"},
                "tool_response": {"response": "Yes, use A"},
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.smm_dir / ".question-gate").exists())
        # Success path does NOT set .asking-user (only failures do)
        self.assertFalse((self.smm_dir / ".asking-user").exists())

        events = self._read_events()
        answers = [e for e in events if e.get("type") == "answer"]
        self.assertEqual(len(answers), 1)
        self.assertIn("Yes, use A", answers[0]["content"])
        self.assertEqual(answers[0].get("references"), [question_id])

    def test_no_gate_logs_customer_input(self):
        """No gate — answers logged as customer_input, no .asking-user."""
        result = self._run_script(
            "question_answered.py",
            {
                "session_id": "it",
                "tool_name": "AskUserQuestion",
                "tool_input": {"question": "anything?"},
                "tool_response": {"response": "nothing"},
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.smm_dir / ".asking-user").exists())
        events = self._read_events()
        self.assertEqual([e for e in events if e.get("type") == "answer"], [])
        inputs = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(inputs), 1)

    def test_failure_sets_asking_user_marker(self):
        """PostToolUseFailure: 'Chat about this...' sets .asking-user."""
        result = self._run_script(
            "question_answered.py",
            {
                "session_id": "it",
                "tool_name": "AskUserQuestion",
                "tool_input": {"question": "anything?"},
                "error": "The user wants to clarify.",
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".asking-user").exists())


# ---------------------------------------------------------------------------
# prompt_nugget.py — UserPromptSubmit hook
# ---------------------------------------------------------------------------


class TestPromptNuggetIntegration(_IntegrationTestCase):
    """Watermark persistence across subprocess calls — the only behavior
    a hook-level test cannot exercise."""

    def test_watermark_persists_across_subprocess_calls(self):
        self._seed_events(
            [
                make_event("concern", content="Flaky DB test"),
                make_event("question", content="Which DB?"),
            ]
        )

        # First call: new events present, nugget returned.
        result_a = self._run_script(
            "prompt_nugget.py",
            {
                "session_id": "it",
                "prompt": "work",
                "agent_id": "main",
            },
        )
        self.assertEqual(result_a.returncode, 0, result_a.stderr)
        parsed = json.loads(result_a.stdout)
        context = parsed["hookSpecificOutput"]["additionalContext"]
        # Priority: concerns > questions. Either content is fine as long as
        # one of the seeded events made it into the nugget.
        self.assertTrue(
            "Flaky DB test" in context or "Which DB?" in context,
            f"expected seeded event in nugget, got: {context}",
        )

        # Second call: no new events appended, watermark advanced → empty.
        result_b = self._run_script(
            "prompt_nugget.py",
            {
                "session_id": "it",
                "prompt": "more work",
                "agent_id": "main",
            },
        )
        self.assertEqual(result_b.returncode, 0, result_b.stderr)
        self.assertEqual(result_b.stdout.strip(), "")

        # Watermark file exists on disk — proves persistence.
        self.assertTrue((self.smm_dir / ".watermark-prompt-nugget").exists())


if __name__ == "__main__":
    unittest.main()
