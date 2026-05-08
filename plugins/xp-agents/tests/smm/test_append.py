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
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_STATUS


class TestAppendIntegration(_TempRepoTestCase):
    """Integration tests using append.sh subprocess."""

    def setUp(self):
        self._clear_events()

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
        self.assertEqual(events[0]["type"], EVENT_TYPE_STATUS)
        self.assertEqual(events[0]["working_on"], ["f.py"])

    def test_append_prints_event_id_on_success(self):
        # The xp-close-reviewer agent reads the event_id from stdout to
        # populate the next commit's `Resolves-Event:` trailer. Pinning
        # the contract so future _append_impl edits can't silently break
        # the handoff. Assert EXACT match (not .strip()) so the post-write
        # duplicate-debt probe can't sneak prints onto stdout — even a
        # lone trailing newline would shift this assertion.
        r = self._run_append(
            "--type",
            "status",
            "--agent",
            "main",
            "--content",
            "working",
            "--working-on",
            "[]",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        # Stdout must be exactly `<id>\n` — nothing before, nothing after.
        # Confirms the probe (and any future post-write step) routes its
        # output to stderr.
        self.assertEqual(r.stdout, events[0]["id"] + "\n")

    def test_stdout_stays_single_line_when_duplicate_probe_fires(self):
        # Plan-reviewer concern 5dcd462aa9fa: the post-write duplicate-debt
        # probe also calls append_event for its advisory record. If the
        # probe ever routed through main() (which prints), stdout would
        # become `<original-id>\n<advisory-id>\n` and silently break the
        # close-reviewer's single-line stdout contract.
        # Identical content triggers the token-Jaccard match in
        # duplicate_debt_probe — change the threshold there and this
        # test will silently stop exercising the probe (caught by the
        # 3-event assertion below).
        DUP_CONTENT = "Refactor the foo bar baz module to extract the quux helper"
        r1 = self._run_append(
            "--type",
            "debt",
            "--agent",
            "main",
            "--content",
            DUP_CONTENT,
            "--files",
            '["foo.py"]',
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self._run_append(
            "--type",
            "debt",
            "--agent",
            "main",
            "--content",
            DUP_CONTENT,
            "--files",
            '["foo.py"]',
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(r2.stderr, "", "Probe must not leak to stderr either")
        events = self._read_events()
        # 2 debts + 1 probe-fired advisory. If only 2, the probe
        # didn't fire — fail loudly so the pin can't false-pass.
        self.assertEqual(
            len(events),
            3,
            f"Expected 3 events (2 debts + 1 probe-fired advisory); got "
            f"{len(events)}. Probe did not fire — test no longer covers "
            f"the duplicate-stdout risk it was written to pin.",
        )
        # Exact-match pins the contract: only the new event's id, no
        # advisory id leaking through.
        self.assertEqual(r2.stdout, events[1]["id"] + "\n")

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
        status = events_of_type(events, EVENT_TYPE_STATUS)
        self.assertEqual(status[-1]["working_on"], [])

    def test_reject_missing_topic(self):
        r = self._run_append("--type", "decision", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_reject_missing_priority(self):
        r = self._run_append("--type", "question", "--agent", "main", "--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_event_has_id_and_timestamp(self):
        r = self._run_append(
            "--type",
            "discovery",
            "--agent",
            "main",
            "--content",
            "found it",
            "--references",
            '["assumption-id"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events()
        event = events[0]
        self.assertRegex(event["id"], r"^[0-9a-f]{12}$")
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
            [
                "--type",
                "discovery",
                "--agent",
                "m",
                "--content",
                "x",
                "--references",
                '["assumption-id"]',
            ],
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
            [
                "--type",
                "answer",
                "--agent",
                "m",
                "--content",
                "x",
                "--references",
                '["question-id"]',
            ],
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
