#!/usr/bin/env python3
"""Tests for the test_layout surface in system_context schema.

Scope: validator coverage + enum lock for the optional top-level
`test_layout` field added by story-002 (sprint-107). The pre-existing
system_context schema tests live in tests/engine/; this file covers
only the new test_layout surface and is referenced by the story-002
acceptance command.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from system_context_entry_validators import (
    _VALID_TEST_LAYOUT_CONVENTIONS,
    _validate_test_layout,
)


class TestTestLayoutValidator(unittest.TestCase):
    def test_valid_minimal_layout(self) -> None:
        errors = _validate_test_layout({"convention": "python_pytest"})
        self.assertEqual(errors, [])

    def test_missing_convention_is_rejected(self) -> None:
        errors = _validate_test_layout({})
        self.assertTrue(any("convention" in e for e in errors), errors)

    def test_unknown_convention_value_is_rejected(self) -> None:
        errors = _validate_test_layout({"convention": "python_unittest"})
        self.assertTrue(any("python_unittest" in e for e in errors), errors)


class TestTestLayoutConventionEnumLock(unittest.TestCase):
    """Lock the 12-entry convention enum (interface contract with story-001)."""

    def test_enum_is_exactly_twelve_locked_strings(self) -> None:
        self.assertEqual(
            _VALID_TEST_LAYOUT_CONVENTIONS,
            frozenset(
                {
                    "python_pytest",
                    "go_native",
                    "js_unit",
                    "rust_cargo",
                    "ruby_rspec",
                    "java_junit",
                    "csharp_xunit",
                    "elixir_exunit",
                    "swift_xctest",
                    "php_phpunit",
                    "unknown",
                    "custom",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
