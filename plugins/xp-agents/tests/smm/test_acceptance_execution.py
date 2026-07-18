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
    validate_per_ac_verify,
)

_PREFIX = "stories[0].acceptance_execution"

_AC_PREFIX = "stories[0].acceptance_criteria[0]"


def _v(ae: object) -> list[str]:
    return validate_acceptance_execution(ae, _PREFIX)


def _vac(item: object) -> list[str]:
    return validate_per_ac_verify(item, _AC_PREFIX)


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


class TestValidatePins(unittest.TestCase):
    """Story-level acceptance_execution.pins: declared regression-pin paths."""

    def test_absent_pins_is_valid(self):
        self.assertEqual(_v({"type": "pytest", "command": "pytest tests/"}), [])

    def test_list_of_strings_pins_is_valid(self):
        ae = {
            "type": "pytest",
            "command": "pytest tests/",
            "pins": ["tests/x_test.py", "tests/y_test.py"],
        }
        self.assertEqual(_v(ae), [])

    def test_non_list_pins_rejected(self):
        errors = _v(
            {"type": "pytest", "command": "pytest tests/", "pins": "tests/x_test.py"}
        )
        self.assertTrue(any("pins" in e for e in errors), errors)

    def test_non_string_entry_in_pins_rejected(self):
        errors = _v(
            {"type": "pytest", "command": "pytest tests/", "pins": ["tests/x.py", 1]}
        )
        self.assertTrue(any("pins" in e for e in errors), errors)


class TestManualOptionalCommand(unittest.TestCase):
    """A type==manual block may omit the command/commands block — its check is
    human/agent judgment, optionally with a runnable confirmation. Every other
    type still requires exactly one of command xor commands."""

    def test_manual_without_command_is_valid(self):
        self.assertEqual(_v({"type": "manual"}), [])

    def test_manual_with_steps_only_is_valid(self):
        ae = {"type": "manual", "steps": ["Deploy to staging", "Confirm redirect"]}
        self.assertEqual(_v(ae), [])

    def test_manual_with_command_is_valid(self):
        # A manual block MAY carry a runnable confirmation command.
        ae = {"type": "manual", "command": "git ls-files --error-unmatch docs/x.md"}
        self.assertEqual(_v(ae), [])

    def test_non_manual_without_command_still_rejected(self):
        errors = _v({"type": "pytest"})
        self.assertTrue(any("command" in e and "commands" in e for e in errors), errors)

    def test_manual_with_both_command_and_commands_still_rejected(self):
        # The xor still holds when a manual block DOES carry a command block.
        ae = {"type": "manual", "command": "true", "commands": ["true"]}
        errors = _v(ae)
        self.assertTrue(any("command" in e and "commands" in e for e in errors), errors)


class TestValidateSteps(unittest.TestCase):
    """Optional `steps: list[str]` — structured human/agent steps for a manual
    check, distinct from runnable `commands`."""

    def test_absent_steps_is_valid(self):
        self.assertEqual(_v({"type": "manual"}), [])

    def test_list_of_strings_steps_is_valid(self):
        ae = {"type": "manual", "steps": ["step one", "step two"]}
        self.assertEqual(_v(ae), [])

    def test_non_list_steps_rejected(self):
        errors = _v({"type": "manual", "steps": "do the thing"})
        self.assertTrue(any("steps" in e for e in errors), errors)

    def test_non_string_entry_in_steps_rejected(self):
        errors = _v({"type": "manual", "steps": ["ok", 42]})
        self.assertTrue(any("steps" in e for e in errors), errors)

    def test_steps_alongside_command_is_valid(self):
        ae = {"type": "manual", "command": "true", "steps": ["also confirm by eye"]}
        self.assertEqual(_v(ae), [])


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

    def test_render_command_less_manual_with_steps_does_not_raise(self):
        # A manual block with no command must not KeyError in the renderer
        # (extract_commands used to run unconditionally). Steps are rendered.
        lines: list[str] = []
        render_acceptance_execution(
            {"type": "manual", "steps": ["Deploy to staging", "Confirm redirect"]},
            lines,
        )
        rendered = "\n".join(lines)
        self.assertIn("**Type:** manual", rendered)
        self.assertNotIn("**Command:**", rendered)
        self.assertNotIn("**Commands:**", rendered)
        self.assertIn("**Steps:**", rendered)
        self.assertIn("Deploy to staging", rendered)
        self.assertIn("Confirm redirect", rendered)

    def test_render_manual_with_command_and_steps(self):
        lines: list[str] = []
        render_acceptance_execution(
            {
                "type": "manual",
                "command": "git ls-files --error-unmatch docs/x.md",
                "steps": ["Then eyeball the rendered doc"],
            },
            lines,
        )
        rendered = "\n".join(lines)
        self.assertIn("**Command:** `git ls-files --error-unmatch docs/x.md`", rendered)
        self.assertIn("**Steps:**", rendered)
        self.assertIn("Then eyeball the rendered doc", rendered)


class TestValidatePerAcVerify(unittest.TestCase):
    """Per-AC verify: an AC item is `str` (manual) or an object with a
    description, optional surface, and an optional command/commands verify
    block reusing the story-level xor (minus the required `type`)."""

    def test_bare_string_item_is_valid(self):
        self.assertEqual(_vac("Given X, When Y, Then Z"), [])

    def test_object_with_description_only_is_valid(self):
        self.assertEqual(_vac({"description": "manual check, no runner"}), [])

    def test_object_with_single_command_is_valid(self):
        item = {"description": "exports CSV", "command": "pytest tests/test_x.py"}
        self.assertEqual(_vac(item), [])

    def test_object_with_commands_list_is_valid(self):
        item = {
            "description": "exports CSV",
            "commands": ["grep -q FOO f.txt", "pytest tests/test_x.py"],
        }
        self.assertEqual(_vac(item), [])

    def test_object_with_surface_is_valid(self):
        item = {"description": "api works", "surface": "api", "command": "pytest x"}
        self.assertEqual(_vac(item), [])

    def test_object_with_both_command_and_commands_rejected(self):
        item = {
            "description": "x",
            "command": "pytest x",
            "commands": ["pytest x"],
        }
        errors = _vac(item)
        self.assertTrue(any("command" in e and "commands" in e for e in errors), errors)

    def test_object_missing_description_rejected(self):
        errors = _vac({"command": "pytest x"})
        self.assertTrue(any("description" in e for e in errors), errors)

    def test_object_non_string_description_rejected(self):
        errors = _vac({"description": 42})
        self.assertTrue(any("description" in e for e in errors), errors)

    def test_object_non_string_surface_rejected(self):
        errors = _vac({"description": "x", "surface": 7})
        self.assertTrue(any("surface" in e for e in errors), errors)

    def test_object_non_string_command_rejected(self):
        errors = _vac({"description": "x", "command": 42})
        self.assertTrue(any("command" in e for e in errors), errors)

    def test_object_empty_commands_list_rejected(self):
        errors = _vac({"description": "x", "commands": []})
        self.assertTrue(
            any("commands" in e and "empty" in e.lower() for e in errors), errors
        )

    def test_neither_string_nor_dict_rejected(self):
        errors = _vac(42)
        self.assertTrue(any("must be a string or" in e for e in errors), errors)


class TestValidatePerAcVerifySurfaceFK(unittest.TestCase):
    """When `valid_surfaces` is supplied, an object AC's `surface` must be one
    of those names; None keeps the FK shape-only (back-compat)."""

    def _vac_fk(self, item: object, valid_surfaces) -> list[str]:
        return validate_per_ac_verify(item, _AC_PREFIX, valid_surfaces=valid_surfaces)

    def test_surface_in_set_is_valid(self):
        item = {"description": "api works", "surface": "api"}
        self.assertEqual(self._vac_fk(item, frozenset({"api", "cli"})), [])

    def test_surface_not_in_set_rejected(self):
        item = {"description": "api works", "surface": "ghost"}
        errors = self._vac_fk(item, frozenset({"api", "cli"}))
        self.assertTrue(any("surface" in e and "ghost" in e for e in errors), errors)

    def test_none_valid_surfaces_skips_fk(self):
        item = {"description": "api works", "surface": "ghost"}
        self.assertEqual(self._vac_fk(item, None), [])

    def test_absent_surface_with_set_is_valid(self):
        item = {"description": "manual check"}
        self.assertEqual(self._vac_fk(item, frozenset({"api"})), [])

    def test_bare_string_with_set_is_valid(self):
        errors = self._vac_fk("Given X, When Y, Then Z", frozenset({"api"}))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
