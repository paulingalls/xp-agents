#!/usr/bin/env python3
"""Tests for _append_impl.validate_event -- event schema validation.

Split from test_init.py -- unit tests for event validation (no subprocess).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import EVENT_TYPE_CUSTOMER_INPUT


class TestValidateEvent(unittest.TestCase):
    """Tests for _append_impl.validate_event (unit tests, no subprocess)."""

    def _base_event(self, **overrides) -> dict:
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": EVENT_TYPE_CUSTOMER_INPUT,
            "agent_id": "main",
            "content": "test",
            "schema_version": 1,
        }
        event.update(overrides)
        return event

    def test_valid_customer_input(self):
        errors = _append_impl.validate_event(self._base_event())
        self.assertEqual(errors, [])

    def test_valid_status(self):
        event = self._base_event(type="status", working_on=["src/app.ts"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_decision(self):
        event = self._base_event(type="decision", topic="database")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_convention(self):
        event = self._base_event(type="convention", topic="naming")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_concern_with_severity(self):
        event = self._base_event(type="concern", severity="high")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_concern_without_severity(self):
        event = self._base_event(type="concern")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_discovery(self):
        event = self._base_event(type="discovery", references=["some-id"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_discovery_missing_references(self):
        event = self._base_event(type="discovery")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_discovery_empty_references(self):
        event = self._base_event(type="discovery", references=[])
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_valid_question(self):
        event = self._base_event(type="question", priority="\U0001f534")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_answer(self):
        event = self._base_event(type="answer", references=["some-id"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_answer_missing_references(self):
        event = self._base_event(type="answer")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_answer_empty_references(self):
        event = self._base_event(type="answer", references=[])
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_valid_assumption(self):
        event = self._base_event(type="assumption")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_session_end_minimal(self):
        event = self._base_event(type="session_end")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_session_end_full(self):
        event = self._base_event(
            type="session_end",
            duration_seconds=3600.5,
            event_count=42,
            unresolved_items=["q1"],
            working_on=["file.py"],
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_commit_minimal(self):
        event = self._base_event(type="commit")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_commit_full(self):
        event = self._base_event(
            type="commit",
            files=["src/app.py", "tests/test_app.py"],
            metadata={
                "commit_hash": "abc1234def5678",
                "code_commit": True,
            },
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_commit_files_must_be_list(self):
        event = self._base_event(type="commit", files="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("files" in e for e in errors))

    def test_valid_retrospective(self):
        event = self._base_event(
            type="retrospective",
            keep=[{"content": "Good TDD", "values": ["feedback"]}],
            fix=[
                {
                    "content": "Slow reviews",
                    "xp_value": "communication",
                }
            ],
        )
        event["try"] = [{"content": "Mob programming"}]
        self.assertEqual(_append_impl.validate_event(event), [])

    # --- Missing required fields ---

    def test_missing_universal_field(self):
        event = self._base_event()
        del event["agent_id"]
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("agent_id" in e for e in errors))

    def test_invalid_type(self):
        event = self._base_event(type="invalid")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("Invalid event type" in e for e in errors))

    def test_status_missing_working_on(self):
        event = self._base_event(type="status")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("working_on" in e for e in errors))

    def test_decision_missing_topic(self):
        event = self._base_event(type="decision")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("topic" in e for e in errors))

    def test_convention_missing_topic(self):
        event = self._base_event(type="convention")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("topic" in e for e in errors))

    def test_question_missing_priority(self):
        event = self._base_event(type="question")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("priority" in e for e in errors))

    # --- Invalid field values ---

    def test_invalid_severity(self):
        event = self._base_event(type="concern", severity="critical")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("severity" in e for e in errors))

    def test_invalid_priority(self):
        event = self._base_event(type="question", priority="urgent")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("priority" in e for e in errors))

    def test_decision_bare_retro_try_adopted_rejected(self):
        """Bare 'retro-try-adopted' must be rejected."""
        event = self._base_event(type="decision", topic="retro-try-adopted")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("retro-try-" in e for e in errors))

    def test_decision_retro_try_with_slug_accepted(self):
        """Specific retro-try-<slug> topics are valid."""
        event = self._base_event(type="decision", topic="retro-try-answer-recording")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_decision_retro_try_with_short_slug_accepted(self):
        event = self._base_event(type="decision", topic="retro-try-fix-gate")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_decision_non_retro_topic_unaffected(self):
        """Normal topics should not be affected."""
        event = self._base_event(type="decision", topic="database-choice")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_working_on_wrong_type(self):
        event = self._base_event(type="status", working_on="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("array" in e for e in errors))

    def test_references_wrong_type(self):
        event = self._base_event(references="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("references" in e for e in errors))

    def test_retrospective_keep_missing_content(self):
        event = self._base_event(type="retrospective", keep=[{"values": ["x"]}])
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("content" in e for e in errors))

    # --- New M5.2 types: goal, debt, customer_intent ---

    def test_valid_goal(self):
        event = self._base_event(type="goal")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_debt(self):
        event = self._base_event(type="debt", files=["src/legacy.py"])
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_debt_missing_files(self):
        event = self._base_event(type="debt")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("files" in e for e in errors))

    def test_debt_files_wrong_type(self):
        event = self._base_event(type="debt", files="not-a-list")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("array" in e for e in errors))

    def test_valid_customer_intent(self):
        event = self._base_event(type="customer_intent", intent_status="open")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_customer_intent_missing_intent_status(self):
        event = self._base_event(type="customer_intent")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("intent_status" in e for e in errors))

    def test_customer_intent_invalid_intent_status(self):
        event = self._base_event(type="customer_intent", intent_status="invalid")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("intent_status" in e for e in errors))

    def test_customer_intent_all_statuses_valid(self):
        for status in ("open", "delivered", "superseded"):
            with self.subTest(status=status):
                event = self._base_event(type="customer_intent", intent_status=status)
                self.assertEqual(_append_impl.validate_event(event), [])

    # --- Sprint event type ---

    def test_valid_sprint_start(self):
        event = self._base_event(
            type="sprint",
            metadata={
                "sprint_id": "sprint-001",
                "action": "start",
                "goal": "Ship v1",
            },
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_sprint_end(self):
        event = self._base_event(
            type="sprint",
            metadata={
                "sprint_id": "sprint-001",
                "action": "end",
                "stories_planned": 10,
                "stories_delivered": 8,
                "stories_carried": 2,
            },
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_sprint_missing_metadata(self):
        event = self._base_event(type="sprint")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("metadata" in e for e in errors))

    def test_sprint_metadata_missing_sprint_id(self):
        event = self._base_event(type="sprint", metadata={"action": "start"})
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("sprint_id" in e for e in errors))

    def test_sprint_metadata_missing_action(self):
        event = self._base_event(
            type="sprint",
            metadata={"sprint_id": "sprint-001"},
        )
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("action" in e for e in errors))

    def test_sprint_invalid_action(self):
        event = self._base_event(
            type="sprint",
            metadata={
                "sprint_id": "sprint-001",
                "action": "pause",
            },
        )
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("action" in e for e in errors))

    def test_sprint_empty_sprint_id(self):
        event = self._base_event(
            type="sprint",
            metadata={"sprint_id": "", "action": "start"},
        )
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("sprint_id" in e for e in errors))

    # --- All three priority emojis ---

    def test_priority_red(self):
        event = self._base_event(type="question", priority="\U0001f534")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_priority_yellow(self):
        event = self._base_event(type="question", priority="\U0001f7e1")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_priority_green(self):
        event = self._base_event(type="question", priority="\U0001f7e2")
        self.assertEqual(_append_impl.validate_event(event), [])


if __name__ == "__main__":
    unittest.main()
