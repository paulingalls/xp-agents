#!/usr/bin/env python3
"""Tests for the shared acceptance_execution validator/renderer.

Story-001 (sprint-062): the schema must accept a multi-command shape
(`commands: list[str]`) alongside the back-compat single-command shape
(`command: str`). Exactly one must be present (xor); both or neither
is a validation error.

These tests pin both shapes so a future schema tweak that drops either
half fails loudly.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _acceptance_execution import (
    render_acceptance_execution,
    validate_acceptance_execution,
)

_PREFIX = "stories[0].acceptance_execution"


def _v(ae: object) -> list[str]:
    return validate_acceptance_execution(ae, _PREFIX)


class TestValidateBackCompatCommand(unittest.TestCase):
    """Single `command: str` shape — pre-existing behavior must keep working."""

    def test_minimal_command_is_valid(self):
        self.assertEqual(_v({"type": "pytest", "command": "pytest tests/"}), [])

    def test_command_with_setup_and_notes_is_valid(self):
        ae = {
            "type": "pytest",
            "command": "pytest tests/",
            "setup": "docker compose up -d",
            "notes": "Backend on :3000",
        }
        self.assertEqual(_v(ae), [])

    def test_non_string_command_rejected(self):
        errors = _v({"type": "pytest", "command": 42})
        self.assertTrue(any("command" in e for e in errors), errors)


class TestValidateCommandsList(unittest.TestCase):
    """New `commands: list[str]` shape introduced in sprint-062 story-001."""

    def test_single_entry_commands_is_valid(self):
        ae = {"type": "pytest", "commands": ["pytest tests/"]}
        self.assertEqual(_v(ae), [])

    def test_multi_entry_commands_is_valid(self):
        ae = {
            "type": "pytest",
            "commands": [
                "grep -q FOO file.txt",
                "pytest tests/",
                "bash scripts/check.sh",
            ],
        }
        self.assertEqual(_v(ae), [])

    def test_empty_commands_list_rejected(self):
        errors = _v({"type": "pytest", "commands": []})
        self.assertTrue(
            any("commands" in e and "empty" in e.lower() for e in errors), errors
        )

    def test_non_list_commands_rejected(self):
        errors = _v({"type": "pytest", "commands": "pytest tests/"})
        self.assertTrue(any("commands" in e for e in errors), errors)

    def test_non_string_entry_in_commands_rejected(self):
        errors = _v({"type": "pytest", "commands": ["pytest tests/", 42]})
        self.assertTrue(any("commands" in e for e in errors), errors)


class TestValidateXorRequirement(unittest.TestCase):
    """Exactly one of `command` xor `commands` must be present."""

    def test_neither_present_rejected(self):
        errors = _v({"type": "pytest"})
        self.assertTrue(any("command" in e and "commands" in e for e in errors), errors)

    def test_both_present_rejected(self):
        ae = {
            "type": "pytest",
            "command": "pytest tests/",
            "commands": ["pytest tests/"],
        }
        errors = _v(ae)
        self.assertTrue(any("command" in e and "commands" in e for e in errors), errors)


class TestValidateInvariantsUnchanged(unittest.TestCase):
    """Type/setup/notes invariants survive the xor change."""

    def test_missing_type_rejected(self):
        errors = _v({"command": "pytest tests/"})
        self.assertTrue(any("type" in e for e in errors), errors)

    def test_non_dict_rejected(self):
        errors = _v("not a dict")
        self.assertTrue(any("must be an object" in e for e in errors), errors)

    def test_non_string_setup_rejected(self):
        errors = _v({"type": "pytest", "command": "pytest", "setup": 1})
        self.assertTrue(any("setup" in e for e in errors), errors)

    def test_non_string_notes_rejected(self):
        errors = _v({"type": "pytest", "command": "pytest", "notes": 1})
        self.assertTrue(any("notes" in e for e in errors), errors)


class TestRenderCommands(unittest.TestCase):
    """`render_acceptance_execution` must handle both shapes."""

    def test_render_single_command_unchanged(self):
        lines: list[str] = []
        render_acceptance_execution(
            {"type": "pytest", "command": "pytest tests/"}, lines
        )
        rendered = "\n".join(lines)
        self.assertIn("**Command:** `pytest tests/`", rendered)

    def test_render_commands_list_numbered(self):
        lines: list[str] = []
        render_acceptance_execution(
            {
                "type": "pytest",
                "commands": [
                    "grep -q FOO file.txt",
                    "pytest tests/",
                ],
            },
            lines,
        )
        rendered = "\n".join(lines)
        self.assertIn("**Commands:**", rendered)
        self.assertIn("`grep -q FOO file.txt`", rendered)
        self.assertIn("`pytest tests/`", rendered)


if __name__ == "__main__":
    unittest.main()
