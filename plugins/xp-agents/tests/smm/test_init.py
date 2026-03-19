#!/usr/bin/env python3
"""Tests for SMM initialization and event validation.

Split from smm/test_smm.py — covers TestInit and TestValidateEvent.
"""

import sys
import unittest
from pathlib import Path

# Path setup — allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from conftest import _TempRepoTestCase


class TestInit(_TempRepoTestCase):
    """Tests for smm/init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def setUp(self) -> None:
        # Reset events.jsonl before each test to prevent state leakage
        (self.smm_dir / "events.jsonl").write_text("")

    def test_init_succeeds(self):
        result = self._run_init()
        self.assertEqual(result.returncode, 0)
        smm_dir = result.stdout.strip()
        self.assertTrue(Path(smm_dir).is_dir())

    def test_init_idempotent(self):
        r1 = self._run_init()
        r2 = self._run_init()
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_init_creates_structure(self):
        smm_dir = self._get_smm_dir()
        self.assertTrue((smm_dir / "events.jsonl").exists())
        self.assertTrue((smm_dir / "events.lock").exists())
        self.assertTrue((smm_dir / "retrospectives").is_dir())

    def test_init_events_file_permissions(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        mode = events_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.jsonl mode is {oct(mode)}")

    def test_init_lock_file_permissions(self):
        smm_dir = self._get_smm_dir()
        lock_file = smm_dir / "events.lock"
        mode = lock_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.lock mode is {oct(mode)}")

    def test_init_smm_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        mode = smm_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"SMM dir mode is {oct(mode)}")

    def test_init_retrospectives_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        retro_dir = smm_dir / "retrospectives"
        mode = retro_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"retrospectives dir mode is {oct(mode)}")

    def test_init_does_not_truncate_existing(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        events_file.write_text("existing content\n")

        self._run_init()

        self.assertEqual(events_file.read_text(), "existing content\n")


class TestValidateEvent(unittest.TestCase):
    """Tests for _append_impl.validate_event (unit tests, no subprocess)."""

    def _base_event(self, **overrides) -> dict:
        event = {
            "id": "12345678-1234-4123-8123-123456789abc",
            "ts": "2026-03-12T00:00:00+00:00",
            "type": "customer_input",
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
        event = self._base_event(type="discovery")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_question(self):
        event = self._base_event(type="question", priority="\U0001f534")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_answer(self):
        event = self._base_event(type="answer", references=["some-id"])
        self.assertEqual(_append_impl.validate_event(event), [])

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
            final_status_recorded=True,
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_retrospective(self):
        event = self._base_event(
            type="retrospective",
            keep=[{"content": "Good TDD", "values": ["feedback"]}],
            fix=[{"content": "Slow reviews", "xp_value": "communication"}],
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
