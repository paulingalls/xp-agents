#!/usr/bin/env python3
"""Tests for SMM Foundation (Milestone 1).

Tests init.sh, append.sh, _append_impl.py, and schema.json.
Run with: python3 -m pytest smm/test_smm.py -v  (or just python3 smm/test_smm.py)
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

# Allow importing _append_impl from the same directory
sys.path.insert(0, str(Path(__file__).parent))
import _append_impl

ROOT = Path(__file__).resolve().parent.parent
INIT_SH = ROOT / "smm" / "init.sh"
APPEND_SH = ROOT / "smm" / "append.sh"


def run_append(*args: str) -> subprocess.CompletedProcess:
    """Run append.sh with given arguments."""
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    return subprocess.run(
        [str(APPEND_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )


def run_init() -> subprocess.CompletedProcess:
    """Run init.sh and return the result."""
    return subprocess.run(
        [str(INIT_SH)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def get_smm_dir() -> str:
    """Get the SMM directory path."""
    result = run_init()
    assert result.returncode == 0, f"init.sh failed: {result.stderr}"
    return result.stdout.strip()


class TestInit(unittest.TestCase):
    """Tests for smm/init.sh."""

    def test_init_succeeds(self):
        result = run_init()
        self.assertEqual(result.returncode, 0)
        smm_dir = result.stdout.strip()
        self.assertTrue(Path(smm_dir).is_dir())

    def test_init_idempotent(self):
        r1 = run_init()
        r2 = run_init()
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_init_creates_structure(self):
        smm_dir = Path(get_smm_dir())
        self.assertTrue((smm_dir / "events.jsonl").exists())
        self.assertTrue((smm_dir / "events.lock").exists())
        self.assertTrue((smm_dir / "retrospectives").is_dir())

    def test_init_does_not_truncate_existing(self):
        smm_dir = get_smm_dir()
        events_file = Path(smm_dir) / "events.jsonl"
        events_file.write_text("existing content\n")

        run_init()

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

    def test_valid_pair_guidance(self):
        event = self._base_event(type="pair_guidance", tool_name="Write")
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

    def test_pair_guidance_missing_tool_name(self):
        event = self._base_event(type="pair_guidance")
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("tool_name" in e for e in errors))

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


class TestAppendIntegration(unittest.TestCase):
    """Integration tests using append.sh subprocess."""

    @classmethod
    def setUpClass(cls):
        cls.smm_dir = get_smm_dir()
        cls.events_file = Path(cls.smm_dir) / "events.jsonl"

    def setUp(self):
        # Clear events before each test
        self.events_file.write_text("")

    def _read_events(self) -> list[dict]:
        lines = self.events_file.read_text().strip().split("\n")
        return [json.loads(line) for line in lines if line]

    def test_append_status(self):
        r = run_append(
            "--type",
            "status",
            "--agent",
            "main",
            "--content",
            "working",
            "--working-on",
            '["f.py"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "status")
        self.assertEqual(events[0]["working_on"], ["f.py"])

    def test_append_question_with_emoji(self):
        r = run_append(
            "--type",
            "question",
            "--agent",
            "main",
            "--content",
            "Which DB?",
            "--priority",
            "\U0001f534",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["priority"], "\U0001f534")

    def test_append_decision_with_topic(self):
        r = run_append(
            "--type",
            "decision",
            "--agent",
            "main",
            "--content",
            "Use Postgres",
            "--topic",
            "database",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["topic"], "database")

    def test_append_with_references(self):
        r = run_append(
            "--type",
            "answer",
            "--agent",
            "main",
            "--content",
            "Yes",
            "--references",
            '["id-1","id-2"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(events[0]["references"], ["id-1", "id-2"])

    def test_reject_invalid_type(self):
        r = run_append("--type", "invalid", "--agent", "main", "--content", "bad")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_working_on(self):
        r = run_append("--type", "status", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_topic(self):
        r = run_append("--type", "decision", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_priority(self):
        r = run_append("--type", "question", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_tool_name(self):
        r = run_append("--type", "pair_guidance", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_event_has_uuid_and_timestamp(self):
        r = run_append(
            "--type", "discovery", "--agent", "main", "--content", "found it"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        event = events[0]
        # UUID v4 format
        self.assertRegex(
            event["id"],
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        # ISO 8601 with timezone
        self.assertIn("T", event["ts"])
        self.assertIn("+", event["ts"])

    def test_all_12_types_succeed(self):
        """Ensure every event type can be appended with valid arguments."""
        cases = [
            ["--type", "customer_input", "--agent", "m", "--content", "x"],
            [
                "--type",
                "status",
                "--agent",
                "m",
                "--content",
                "x",
                "--working-on",
                '["f"]',
            ],
            ["--type", "decision", "--agent", "m", "--content", "x", "--topic", "t"],
            ["--type", "convention", "--agent", "m", "--content", "x", "--topic", "t"],
            ["--type", "concern", "--agent", "m", "--content", "x"],
            ["--type", "discovery", "--agent", "m", "--content", "x"],
            [
                "--type",
                "question",
                "--agent",
                "m",
                "--content",
                "x",
                "--priority",
                "\U0001f7e1",
            ],
            ["--type", "answer", "--agent", "m", "--content", "x"],
            ["--type", "assumption", "--agent", "m", "--content", "x"],
            [
                "--type",
                "pair_guidance",
                "--agent",
                "m",
                "--content",
                "x",
                "--tool-name",
                "Write",
            ],
            ["--type", "session_end", "--agent", "m", "--content", "x"],
            ["--type", "retrospective", "--agent", "m", "--content", "x"],
        ]
        for args in cases:
            with self.subTest(type=args[1]):
                r = run_append(*args)
                self.assertEqual(r.returncode, 0, f"Failed for {args[1]}: {r.stderr}")

        events = self._read_events()
        types = {e["type"] for e in events}
        self.assertEqual(len(types), 12, f"Expected 12 types, got {types}")

    def test_session_end_optional_fields(self):
        r = run_append(
            "--type",
            "session_end",
            "--agent",
            "main",
            "--content",
            "done",
            "--duration-seconds",
            "3600.5",
            "--event-count",
            "42",
            "--working-on",
            '["f.py"]',
            "--final-status-recorded",
            "true",
            "--unresolved-items",
            '["q1"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        e = events[0]
        self.assertEqual(e["duration_seconds"], 3600.5)
        self.assertEqual(e["event_count"], 42)
        self.assertEqual(e["working_on"], ["f.py"])
        self.assertTrue(e["final_status_recorded"])
        self.assertEqual(e["unresolved_items"], ["q1"])

    def test_retrospective_nested_objects(self):
        keep = json.dumps(
            [{"content": "Good TDD", "event_refs": ["e1"], "values": ["feedback"]}]
        )
        fix = json.dumps(
            [{"content": "Slow", "event_refs": ["e2"], "xp_value": "communication"}]
        )
        try_items = json.dumps([{"content": "Mob", "event_refs": ["e3"]}])
        r = run_append(
            "--type",
            "retrospective",
            "--agent",
            "main",
            "--content",
            "review",
            "--keep",
            keep,
            "--fix",
            fix,
            "--try-items",
            try_items,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        e = events[0]
        self.assertEqual(e["keep"][0]["content"], "Good TDD")
        self.assertEqual(e["fix"][0]["xp_value"], "communication")
        self.assertEqual(e["try"][0]["content"], "Mob")


class TestConcurrentWrites(unittest.TestCase):
    """Test atomic append under concurrent load."""

    def test_20_concurrent_writes(self):
        smm_dir = get_smm_dir()
        events_file = Path(smm_dir) / "events.jsonl"
        events_file.write_text("")

        def do_append(i: int) -> int:
            r = run_append(
                "--type",
                "status",
                "--agent",
                f"test-{i}",
                "--content",
                f"concurrent {i}",
                "--working-on",
                '["f.py"]',
            )
            return r.returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(do_append, i) for i in range(1, 21)]
            codes = [f.result() for f in futures]

        self.assertTrue(all(c == 0 for c in codes), f"Some appends failed: {codes}")

        lines = events_file.read_text().strip().split("\n")
        self.assertEqual(len(lines), 20, f"Expected 20 lines, got {len(lines)}")

        # All valid JSON
        events = []
        for i, line in enumerate(lines, 1):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                self.fail(f"Invalid JSON on line {i}")

        # All unique agent_ids
        agents = {e["agent_id"] for e in events}
        self.assertEqual(
            len(agents), 20, f"Expected 20 unique agents, got {len(agents)}"
        )


class TestSchemaJson(unittest.TestCase):
    """Validate schema.json structure itself."""

    @classmethod
    def setUpClass(cls):
        schema_path = ROOT / "smm" / "schema.json"
        with open(schema_path) as f:
            cls.schema = json.load(f)

    def test_schema_is_valid_json(self):
        self.assertIsInstance(self.schema, dict)

    def test_schema_has_12_types(self):
        types = self.schema["properties"]["type"]["enum"]
        self.assertEqual(len(types), 12)
        expected = {
            "customer_input",
            "status",
            "decision",
            "convention",
            "concern",
            "discovery",
            "question",
            "answer",
            "assumption",
            "pair_guidance",
            "session_end",
            "retrospective",
        }
        self.assertEqual(set(types), expected)

    def test_universal_required_fields(self):
        required = self.schema["required"]
        for field in ("id", "ts", "type", "agent_id", "content"):
            self.assertIn(field, required)

    def test_type_specific_properties_at_top_level(self):
        """Verify type-specific properties are in top-level properties
        (not buried in allOf/then), so additionalProperties: false works."""
        top_props = self.schema["properties"]
        for field in (
            "working_on",
            "topic",
            "severity",
            "priority",
            "tool_name",
            "duration_seconds",
            "event_count",
            "unresolved_items",
            "final_status_recorded",
            "keep",
            "fix",
            "try",
        ):
            self.assertIn(
                field, top_props, f"'{field}' must be in top-level properties"
            )

    def test_additional_properties_false(self):
        self.assertFalse(self.schema["additionalProperties"])

    def test_conditional_required_fields(self):
        """Verify allOf contains conditional required constraints."""
        all_of = self.schema["allOf"]
        # Find the required fields imposed by conditionals
        conditional_reqs = {}
        for entry in all_of:
            if_clause = entry.get("if", {}).get("properties", {}).get("type", {})
            then_clause = entry.get("then", {})
            type_match = if_clause.get("const") or if_clause.get("enum", [None])
            required = then_clause.get("required", [])
            if required:
                if isinstance(type_match, list):
                    for t in type_match:
                        conditional_reqs[t] = required
                else:
                    conditional_reqs[type_match] = required

        self.assertIn("working_on", conditional_reqs.get("status", []))
        self.assertIn("topic", conditional_reqs.get("decision", []))
        self.assertIn("topic", conditional_reqs.get("convention", []))
        self.assertIn("priority", conditional_reqs.get("question", []))
        self.assertIn("tool_name", conditional_reqs.get("pair_guidance", []))


if __name__ == "__main__":
    unittest.main()
