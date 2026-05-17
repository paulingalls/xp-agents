#!/usr/bin/env python3
"""Behavior tests for system_context_caps_cli — cap-enforcement helpers
extracted from system_context_cli.py.

Existing CLI behavior tests in test_system_context_cli.py (soft warn,
hard refuse, retire-first hint) remain the integration coverage for
the dispatch path. These tests pin the extracted module's own surface:
the _COUNT_CAP_TABLE shape and the cmd_append_to_list contract.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import system_context_caps_cli
from system_context_schema import (
    ACCEPTANCE_SURFACES_HARD_CAP,
    ACCEPTANCE_SURFACES_SOFT_CAP,
    CONVENTIONS_HARD_CAP,
    CONVENTIONS_SOFT_CAP,
    MODULES_HARD_CAP,
    MODULES_SOFT_CAP,
    PRINCIPLES_HARD_CAP,
    PRINCIPLES_SOFT_CAP,
    PROJECT_SPECIFIC_HARD_CAP,
    PROJECT_SPECIFIC_SOFT_CAP,
)


class TestCountCapTable(unittest.TestCase):
    """The cap table pins (soft, hard, retire-subcmd) for every gated list."""

    def test_table_keys_match_gated_list_fields(self):
        self.assertEqual(
            set(system_context_caps_cli._COUNT_CAP_TABLE.keys()),
            {
                "modules",
                "conventions",
                "principles",
                "project_specific",
                "acceptance_surfaces",
            },
        )

    def test_each_entry_is_soft_hard_retire_triple(self):
        for field, value in system_context_caps_cli._COUNT_CAP_TABLE.items():
            soft, hard, retire_cmd = value
            self.assertIsInstance(soft, int, field)
            self.assertIsInstance(hard, int, field)
            self.assertIsInstance(retire_cmd, str, field)
            self.assertLess(soft, hard, f"{field} soft must be < hard")
            self.assertTrue(
                retire_cmd.startswith("retire-"),
                f"{field} retire_cmd must start with retire-",
            )

    def test_cap_values_match_schema_constants(self):
        table = system_context_caps_cli._COUNT_CAP_TABLE
        self.assertEqual(
            table["modules"], (MODULES_SOFT_CAP, MODULES_HARD_CAP, "retire-module")
        )
        self.assertEqual(
            table["conventions"],
            (CONVENTIONS_SOFT_CAP, CONVENTIONS_HARD_CAP, "retire-convention"),
        )
        self.assertEqual(
            table["principles"],
            (PRINCIPLES_SOFT_CAP, PRINCIPLES_HARD_CAP, "retire-principle"),
        )
        self.assertEqual(
            table["project_specific"],
            (
                PROJECT_SPECIFIC_SOFT_CAP,
                PROJECT_SPECIFIC_HARD_CAP,
                "retire-project-specific",
            ),
        )
        self.assertEqual(
            table["acceptance_surfaces"],
            (
                ACCEPTANCE_SURFACES_SOFT_CAP,
                ACCEPTANCE_SURFACES_HARD_CAP,
                "retire-acceptance-surface",
            ),
        )


class TestCmdAppendToListExport(unittest.TestCase):
    """cmd_append_to_list is the public extraction target — exported from
    system_context_caps_cli and re-imported by system_context_cli.
    """

    def test_cmd_append_to_list_is_callable(self):
        self.assertTrue(callable(system_context_caps_cli.cmd_append_to_list))

    def test_cli_module_reimports_helpers(self):
        """system_context_cli.py exposes the same _COUNT_CAP_TABLE object."""
        import system_context_cli

        self.assertIs(
            system_context_cli._COUNT_CAP_TABLE,
            system_context_caps_cli._COUNT_CAP_TABLE,
        )


if __name__ == "__main__":
    unittest.main()
