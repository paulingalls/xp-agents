#!/usr/bin/env python3
"""Wiring tests for system_context_field_cli.

`edit-field` and `_OPTIONAL_TOP_LEVEL_FIELDS` were extracted from
system_context_cli.py when it crossed the 500-line cap. End-to-end behavior is
covered by the CLI suites; these tests pin the extracted module's export
surface, the cli.py re-import shim (same objects, so a `mock.patch` on either
path still bites), and the per-field authoring-check table — sibling of
test_system_context_nested_field_cli / test_system_context_caps_cli.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import system_context_field_cli
from system_context_entry_validators import unknown_surface_key_errors


class TestFieldCliExports(unittest.TestCase):
    def test_commands_are_callable(self):
        for name in ("_cmd_create", "_cmd_edit_field"):
            with self.subTest(command=name):
                self.assertTrue(callable(getattr(system_context_field_cli, name)))

    def test_optional_top_level_fields_membership(self):
        self.assertEqual(
            system_context_field_cli._OPTIONAL_TOP_LEVEL_FIELDS,
            frozenset({"branching_strategy", "acceptance_surfaces", "test_layout"}),
        )

    def test_cli_module_reimports_the_same_objects(self):
        """The shim is identity, not a copy — a `mock.patch` against either
        import path must reach the one object the dispatch table holds."""
        import system_context_cli

        self.assertIs(
            system_context_cli._cmd_edit_field,
            system_context_field_cli._cmd_edit_field,
        )
        self.assertIs(
            system_context_cli._cmd_create,
            system_context_field_cli._cmd_create,
        )
        self.assertIs(
            system_context_cli._OPTIONAL_TOP_LEVEL_FIELDS,
            system_context_field_cli._OPTIONAL_TOP_LEVEL_FIELDS,
        )

    def test_shim_names_are_declared_in_all(self):
        """`__all__` is the aggregator's documented shim surface (and what
        keeps ruff from stripping a re-export that has no local caller)."""
        import system_context_cli

        for name in (
            "_cmd_create",
            "_cmd_edit_field",
            "_OPTIONAL_TOP_LEVEL_FIELDS",
        ):
            with self.subTest(name=name):
                self.assertIn(name, system_context_cli.__all__)


class TestFieldValueChecks(unittest.TestCase):
    """The authoring check is keyed on the FIELD, so every door into the
    generic writer inherits it — including `edit-field <name>` itself."""

    def test_acceptance_surfaces_carries_the_unknown_key_check(self):
        self.assertIs(
            system_context_field_cli._FIELD_VALUE_CHECKS["acceptance_surfaces"],
            unknown_surface_key_errors,
        )

    def test_other_optional_fields_have_no_check(self):
        for field in ("branching_strategy", "test_layout"):
            with self.subTest(field=field):
                self.assertNotIn(field, system_context_field_cli._FIELD_VALUE_CHECKS)


if __name__ == "__main__":
    unittest.main()
