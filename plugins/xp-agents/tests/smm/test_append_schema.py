#!/usr/bin/env python3
"""Tests for schema.json validation and notification helpers.

Split from test_append.py — covers TestSchemaJson, TestNotificationHelpers.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from conftest import _PLUGIN_ROOT, make_event


class TestSchemaJson(unittest.TestCase):
    """Validate schema.json structure itself."""

    @classmethod
    def setUpClass(cls):
        schema_path = _PLUGIN_ROOT / "smm" / "schema.json"
        with open(schema_path) as f:
            cls.schema = json.load(f)

    def test_schema_is_valid_json(self):
        self.assertIsInstance(self.schema, dict)

    def test_schema_has_16_types(self):
        types = self.schema["properties"]["type"]["enum"]
        self.assertEqual(len(types), 16)
        expected = {
            "commit",
            "customer_input",
            "customer_intent",
            "debt",
            "goal",
            "status",
            "decision",
            "convention",
            "concern",
            "discovery",
            "question",
            "answer",
            "assumption",
            "session_end",
            "sprint",
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
            "duration_seconds",
            "event_count",
            "unresolved_items",
            "keep",
            "fix",
            "try",
            "files",
            "intent_status",
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
        self.assertIn("files", conditional_reqs.get("debt", []))
        self.assertIn("intent_status", conditional_reqs.get("customer_intent", []))

    def test_sprint_conditional_requires_metadata(self):
        """Sprint type conditionally requires metadata field."""
        all_of = self.schema["allOf"]
        sprint_req = None
        for entry in all_of:
            if_clause = entry.get("if", {}).get("properties", {}).get("type", {})
            if if_clause.get("const") == "sprint":
                sprint_req = entry.get("then", {}).get("required", [])
        self.assertIsNotNone(sprint_req, "No allOf entry for sprint type")
        self.assertIn("metadata", sprint_req)


class TestNotificationHelpers(unittest.TestCase):
    """Test _detect_platform, _sanitize_notification, _notify_blocking_question."""

    def test_detect_platform_macos(self):
        with patch("resolution.sys") as mock_sys:
            mock_sys.platform = "darwin"
            self.assertEqual(_append_impl._detect_platform(), "macos")

    def test_detect_platform_linux(self):
        with patch("resolution.sys") as mock_sys:
            mock_sys.platform = "linux"
            self.assertEqual(_append_impl._detect_platform(), "linux")

    def test_detect_platform_unknown(self):
        with patch("resolution.sys") as mock_sys:
            mock_sys.platform = "win32"
            self.assertEqual(_append_impl._detect_platform(), "unknown")

    def test_sanitize_strips_quotes(self):
        result = _append_impl._sanitize_notification('He said "hello"')
        self.assertNotIn('"', result)

    def test_sanitize_strips_backslashes(self):
        result = _append_impl._sanitize_notification("path\\to\\file")
        self.assertNotIn("\\", result)

    def test_sanitize_limits_length(self):
        result = _append_impl._sanitize_notification("x" * 300)
        self.assertLessEqual(len(result), 200)

    def test_macos_notification_command(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("resolution._detect_platform", return_value="macos"),
            patch("resolution.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "osascript")

    def test_linux_notification_command(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("resolution._detect_platform", return_value="linux"),
            patch("resolution.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "notify-send")

    def test_non_red_question_no_notification(self):
        event = {
            "type": "question",
            "priority": "\U0001f7e1",
            "content": "Minor question",
        }
        with patch("resolution.subprocess.run") as mock_run:
            _append_impl._notify_blocking_question(event)
            mock_run.assert_not_called()

    def test_non_question_no_notification(self):
        event = {
            "type": "status",
            "working_on": ["file.py"],
            "content": "Working",
        }
        with patch("resolution.subprocess.run") as mock_run:
            _append_impl._notify_blocking_question(event)
            mock_run.assert_not_called()

    def test_notification_failure_doesnt_crash(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": "Which DB?",
        }
        with (
            patch("resolution._detect_platform", return_value="macos"),
            patch(
                "_append_impl.subprocess.run",
                side_effect=OSError("no osascript"),
            ),
        ):
            # Should not raise
            _append_impl._notify_blocking_question(event)

    def test_message_sanitized(self):
        event = {
            "type": "question",
            "priority": "\U0001f534",
            "content": 'He said "drop tables\\n"',
        }
        with (
            patch("resolution._detect_platform", return_value="macos"),
            patch("resolution.subprocess.run") as mock_run,
        ):
            _append_impl._notify_blocking_question(event)
            # The notification message should not contain quotes or backslashes
            args = mock_run.call_args[0][0]
            # osascript -e 'display notification "..." with title "XP Agents"'
            script = args[2]  # the -e argument value
            # Should not contain raw quotes in the notification text
            self.assertNotIn("drop tables\\n", script)


class TestContentBudgets(unittest.TestCase):
    """Tests for per-type content budget enforcement in validate_event()."""

    def test_status_within_budget(self):
        event = make_event("status", content="x" * 200, working_on=[])
        errors = _append_impl.validate_event(event)
        self.assertEqual(errors, [])

    def test_status_over_budget_rejected(self):
        event = make_event("status", content="x" * 201, working_on=[])
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("budget" in e.lower() for e in errors))
        self.assertTrue(any("201" in e for e in errors))
        self.assertTrue(any("200" in e for e in errors))

    def test_commit_uncapped(self):
        event = make_event("commit", content="x" * 5000)
        errors = _append_impl.validate_event(event)
        self.assertEqual(errors, [])

    def test_customer_input_uncapped(self):
        event = make_event("customer_input", content="x" * 10000)
        errors = _append_impl.validate_event(event)
        self.assertEqual(errors, [])

    def test_decision_within_budget(self):
        event = make_event("decision", content="x" * 400)
        errors = _append_impl.validate_event(event)
        self.assertEqual(errors, [])

    def test_decision_over_budget_rejected(self):
        event = make_event("decision", content="x" * 401)
        errors = _append_impl.validate_event(event)
        self.assertTrue(any("budget" in e.lower() for e in errors))

    def test_error_message_actionable(self):
        event = make_event("status", content="x" * 250, working_on=[])
        errors = _append_impl.validate_event(event)
        self.assertEqual(len(errors), 1)
        msg = errors[0]
        self.assertIn("250", msg)
        self.assertIn("200", msg)
        self.assertRegex(msg.lower(), r"shorten|trim")

    def test_all_types_have_budget_entry(self):
        from event_schema import CONTENT_BUDGETS, VALID_TYPES

        for t in VALID_TYPES:
            self.assertIn(t, CONTENT_BUDGETS, f"Missing budget entry for type '{t}'")

    def test_cli_help_shows_budgets(self):
        from event_builder import build_parser

        help_text = build_parser().format_help()
        self.assertIn("Content budgets", help_text)

    def test_schema_json_description_matches_budgets(self):
        """schema.json content description must stay in sync with CONTENT_BUDGETS."""
        from event_schema import CONTENT_BUDGETS

        schema_path = _PLUGIN_ROOT / "smm" / "schema.json"
        with open(schema_path) as f:
            schema = json.load(f)
        desc = schema["properties"]["content"]["description"]
        for event_type, budget in CONTENT_BUDGETS.items():
            if budget is not None:
                self.assertIn(
                    f"{event_type}={budget}",
                    desc,
                    f"schema.json content description missing {event_type}={budget}",
                )
            else:
                self.assertIn(
                    event_type,
                    desc,
                    f"schema.json description missing uncapped {event_type}",
                )


class TestQuestionGate(unittest.TestCase):
    """Test that 🔴 question events create a .question-gate file."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.smm_dir = Path(self._tmpdir)
        (self.smm_dir / "events.jsonl").touch()
        (self.smm_dir / "events.lock").touch()

    def tearDown(self):
        shutil.rmtree(self._tmpdir)

    def _make_event(self, type_: str, **kwargs):
        event = {
            "id": "test-question-id",
            "ts": "2026-04-08T00:00:00+00:00",
            "type": type_,
            "agent_id": "xp-plan-reviewer",
            "content": "Should we use approach A or B?",
            "schema_version": 1,
        }
        event.update(kwargs)
        return event

    def test_blocking_question_creates_gate(self):
        """Appending a 🔴 question should create .question-gate."""
        event = self._make_event("question", priority="\U0001f534")
        with patch("resolution.subprocess.run"):
            _append_impl.append_event(self.smm_dir, event)
        gate = self.smm_dir / ".question-gate"
        self.assertTrue(gate.exists())

    def test_gate_contains_event_id(self):
        """The .question-gate file should contain the question event ID."""
        event = self._make_event("question", priority="\U0001f534")
        with patch("resolution.subprocess.run"):
            _append_impl.append_event(self.smm_dir, event)
        gate = self.smm_dir / ".question-gate"
        self.assertEqual(gate.read_text(), "test-question-id")

    def test_non_blocking_question_no_gate(self):
        """Non-🔴 question should NOT create .question-gate."""
        event = self._make_event("question", priority="\U0001f7e1")
        _append_impl.append_event(self.smm_dir, event)
        gate = self.smm_dir / ".question-gate"
        self.assertFalse(gate.exists())

    def test_non_question_no_gate(self):
        """Non-question events should NOT create .question-gate."""
        event = self._make_event("status", working_on=["file.py"])
        _append_impl.append_event(self.smm_dir, event)
        gate = self.smm_dir / ".question-gate"
        self.assertFalse(gate.exists())


if __name__ == "__main__":
    unittest.main()
