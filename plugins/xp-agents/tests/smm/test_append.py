#!/usr/bin/env python3
"""Tests for SMM append integration operations.

Safety/concurrency tests in test_append_safety.py.
Schema/notification tests in test_append_schema.py.
"""

import json
import sys
import unittest
from pathlib import Path

# Path setup — allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from conftest import _TempRepoTestCase


class TestAppendIntegration(_TempRepoTestCase):
    """Integration tests using append.sh subprocess."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()
        cls.events_file = cls.smm_dir / "events.jsonl"

    def setUp(self):
        # Clear events before each test
        self.events_file.write_text("")

    def _read_events(self) -> list[dict]:
        lines = self.events_file.read_text().strip().split("\n")
        return [json.loads(line) for line in lines if line]

    def test_append_status(self):
        r = self._run_append(
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
        r = self._run_append(
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
        r = self._run_append(
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
        r = self._run_append(
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
        r = self._run_append("--type", "invalid", "--agent", "main", "--content", "bad")
        self.assertNotEqual(r.returncode, 0)

    def test_status_defaults_working_on_to_empty(self):
        r = self._run_append("--type", "status", "--agent", "main", "--content", "x")
        self.assertEqual(r.returncode, 0)
        events = self._read_events()
        status = [e for e in events if e.get("type") == "status"]
        self.assertEqual(status[-1]["working_on"], [])

    def test_reject_missing_topic(self):
        r = self._run_append("--type", "decision", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_priority(self):
        r = self._run_append("--type", "question", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_event_has_uuid_and_timestamp(self):
        r = self._run_append(
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

    def test_all_14_types_succeed(self):
        """Ensure every event type can be appended with valid arguments."""
        cases = [
            ["--type", "customer_input", "--agent", "m", "--content", "x"],
            [
                "--type",
                "customer_intent",
                "--agent",
                "m",
                "--content",
                "x",
                "--intent-status",
                "open",
            ],
            [
                "--type",
                "debt",
                "--agent",
                "m",
                "--content",
                "x",
                "--files",
                '["src/legacy.py"]',
            ],
            ["--type", "goal", "--agent", "m", "--content", "x"],
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
            ["--type", "session_end", "--agent", "m", "--content", "x"],
            ["--type", "retrospective", "--agent", "m", "--content", "x"],
        ]
        for args in cases:
            with self.subTest(type=args[1]):
                r = self._run_append(*args)
                self.assertEqual(r.returncode, 0, f"Failed for {args[1]}: {r.stderr}")

        events = self._read_events()
        types = {e["type"] for e in events}
        self.assertEqual(len(types), 14, f"Expected 14 types, got {types}")

    def test_session_end_optional_fields(self):
        r = self._run_append(
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
            "--unresolved-items",
            '["q1"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        e = events[0]
        self.assertEqual(e["duration_seconds"], 3600.5)
        self.assertEqual(e["event_count"], 42)
        self.assertEqual(e["working_on"], ["f.py"])
        self.assertEqual(e["unresolved_items"], ["q1"])

    def test_retrospective_nested_objects(self):
        keep = json.dumps(
            [{"content": "Good TDD", "event_refs": ["e1"], "values": ["feedback"]}]
        )
        fix = json.dumps(
            [{"content": "Slow", "event_refs": ["e2"], "xp_value": "communication"}]
        )
        try_items = json.dumps([{"content": "Mob", "event_refs": ["e3"]}])
        r = self._run_append(
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


if __name__ == "__main__":
    unittest.main()
