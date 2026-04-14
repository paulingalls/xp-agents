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


class TestSeedSMM(_TempRepoTestCase):
    """Tests for seed_smm.py — default SMM created by init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def _load_smm(self) -> dict:
        import json

        path = self.smm_dir / "shared_mental_model.json"
        return json.loads(path.read_text())

    def test_seed_creates_smm_file(self):
        smm_file = self.smm_dir / "shared_mental_model.json"
        self.assertTrue(
            smm_file.exists(),
            "init.sh should seed shared_mental_model.json",
        )

    def test_seed_has_four_pillars(self):
        smm = self._load_smm()
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertIn(pillar, smm)
            self.assertIsInstance(smm[pillar], list)

    def test_seed_has_xp_constraints(self):
        smm = self._load_smm()
        contents = [e["content"] for e in smm["constraints"]]
        joined = " ".join(contents)
        self.assertIn("TDD", joined)
        self.assertIn("Small commits", joined)

    def test_seed_detects_missing_linter(self):
        """Fresh git repo has no linter — should be flagged as risk."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No linter configured", joined)

    def test_seed_detects_missing_hooks(self):
        """Fresh git repo has no hooks — should be flagged as risk."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No git commit hooks", joined)

    def test_seed_idempotent(self):
        """Running init.sh again does not overwrite existing SMM."""
        smm_file = self.smm_dir / "shared_mental_model.json"
        smm_file.write_text('{"custom": true}')
        self._run_init()
        self.assertEqual(smm_file.read_text(), '{"custom": true}')

    def test_seed_fires_when_only_old_md_exists(self):
        """Old .md present but no JSON → seed fires, .md untouched."""
        json_file = self.smm_dir / "shared_mental_model.json"
        md_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        # Remove the JSON that setUpClass created, leave old .md
        json_file.unlink(missing_ok=True)
        md_file.write_text("# Old markdown SMM\n")
        self._run_init()
        self.assertTrue(json_file.exists(), "JSON should be seeded")
        self.assertTrue(md_file.exists(), "Old .md should be untouched")
        self.assertEqual(md_file.read_text(), "# Old markdown SMM\n")


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
        )
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_commit_minimal(self):
        event = self._base_event(type="commit")
        self.assertEqual(_append_impl.validate_event(event), [])

    def test_valid_commit_full(self):
        event = self._base_event(
            type="commit",
            files=["src/app.py", "tests/test_app.py"],
            metadata={"commit_hash": "abc1234def5678", "code_commit": True},
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

    def test_decision_bare_retro_try_adopted_rejected(self):
        """Bare 'retro-try-adopted' topic must be rejected — use retro-try-<slug>."""
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
        """Normal topics should not be affected by retro-try validation."""
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
            metadata={"sprint_id": "sprint-001", "action": "start", "goal": "Ship v1"},
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
        event = self._base_event(type="sprint", metadata={"sprint_id": "sprint-001"})
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("action" in e for e in errors))

    def test_sprint_invalid_action(self):
        event = self._base_event(
            type="sprint",
            metadata={"sprint_id": "sprint-001", "action": "pause"},
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
