#!/usr/bin/env python3
"""Wiring tests for system_context_nested_field_cli.

The 4 nested-field-edit commands (edit-stack-field, edit-branching-field,
get-stack-field, get-branching-field) were extracted from
system_context_cli.py. Existing CLI behavior tests live in
test_system_context_cli_edit.py + test_system_context_cli_branching.py
and cover dispatch end-to-end. These tests pin the extracted module's
own export surface and the cli.py re-import shim.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import system_context_nested_field_cli


class TestNestedFieldCliExports(unittest.TestCase):
    """The four nested-field-edit commands are exported and callable."""

    def test_module_exports_callables(self):
        for name in (
            "cmd_edit_branching_field",
            "cmd_get_branching_field",
            "cmd_get_stack_field",
            "cmd_edit_stack_field",
        ):
            self.assertTrue(
                callable(getattr(system_context_nested_field_cli, name)),
                f"{name} must be callable",
            )

    def test_cli_module_reimports(self):
        """system_context_cli.py re-imports the same function objects."""
        import system_context_cli

        self.assertIs(
            system_context_cli._cmd_edit_branching_field,
            system_context_nested_field_cli.cmd_edit_branching_field,
        )
        self.assertIs(
            system_context_cli._cmd_get_branching_field,
            system_context_nested_field_cli.cmd_get_branching_field,
        )
        self.assertIs(
            system_context_cli._cmd_get_stack_field,
            system_context_nested_field_cli.cmd_get_stack_field,
        )
        self.assertIs(
            system_context_cli._cmd_edit_stack_field,
            system_context_nested_field_cli.cmd_edit_stack_field,
        )


if __name__ == "__main__":
    unittest.main()
