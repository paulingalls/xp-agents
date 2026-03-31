#!/usr/bin/env python3
"""Tests for schema.json validation and notification helpers.

Split from test_append.py — covers TestSchemaJson, TestNotificationHelpers.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from conftest import _PLUGIN_ROOT


class TestSchemaJson(unittest.TestCase):
    """Validate schema.json structure itself."""

    @classmethod
    def setUpClass(cls):
        schema_path = _PLUGIN_ROOT / "smm" / "schema.json"
        with open(schema_path) as f:
            cls.schema = json.load(f)

    def test_schema_is_valid_json(self):
        self.assertIsInstance(self.schema, dict)

    def test_schema_has_14_types(self):
        types = self.schema["properties"]["type"]["enum"]
        self.assertEqual(len(types), 14)
        expected = {
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
            "final_status_recorded",
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


if __name__ == "__main__":
    unittest.main()
