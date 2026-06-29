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


def _override(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_pattern": "src/**/*.py",
        "stem_extractor": "stem",
        "test_glob": "tests/**/test_{stem}.py",
    }
    base.update(overrides)
    return base


class TestTestLayoutOverrides(unittest.TestCase):
    def test_valid_overrides_empty_list(self) -> None:
        errors = _validate_test_layout({"convention": "python_pytest", "overrides": []})
        self.assertEqual(errors, [])

    def test_valid_custom_with_one_override(self) -> None:
        errors = _validate_test_layout(
            {"convention": "custom", "overrides": [_override()]}
        )
        self.assertEqual(errors, [])

    def test_overrides_with_optional_list_keys(self) -> None:
        errors = _validate_test_layout(
            {
                "convention": "custom",
                "overrides": [
                    _override(
                        skip_basenames=["__init__.py"],
                        skip_suffixes=["_helpers.py"],
                        source_excludes=["src/legacy/**"],
                    )
                ],
            }
        )
        self.assertEqual(errors, [])

    def test_overrides_not_a_list_is_rejected(self) -> None:
        errors = _validate_test_layout(
            {"convention": "python_pytest", "overrides": {"x": 1}}
        )
        self.assertTrue(any("overrides" in e for e in errors), errors)

    def test_override_entry_missing_required_key(self) -> None:
        bad = _override()
        del bad["stem_extractor"]
        errors = _validate_test_layout({"convention": "custom", "overrides": [bad]})
        self.assertTrue(any("stem_extractor" in e for e in errors), errors)

    def test_override_entry_unknown_key_rejected(self) -> None:
        errors = _validate_test_layout(
            {"convention": "custom", "overrides": [_override(random_extra="x")]}
        )
        self.assertTrue(any("random_extra" in e for e in errors), errors)

    def test_override_optional_list_key_wrong_type(self) -> None:
        errors = _validate_test_layout(
            {
                "convention": "custom",
                "overrides": [_override(skip_basenames="not_a_list")],
            }
        )
        self.assertTrue(any("skip_basenames" in e for e in errors), errors)

    def test_override_optional_list_entry_wrong_type(self) -> None:
        errors = _validate_test_layout(
            {"convention": "custom", "overrides": [_override(skip_basenames=[123])]}
        )
        self.assertTrue(any("skip_basenames" in e for e in errors), errors)

    def test_override_required_key_wrong_type(self) -> None:
        errors = _validate_test_layout(
            {"convention": "custom", "overrides": [_override(source_pattern=42)]}
        )
        self.assertTrue(any("source_pattern" in e for e in errors), errors)

    def test_override_entry_not_a_dict(self) -> None:
        errors = _validate_test_layout(
            {"convention": "custom", "overrides": ["not a dict"]}
        )
        self.assertTrue(any("overrides[0]" in e for e in errors), errors)

    def test_unknown_top_level_key_is_rejected(self) -> None:
        errors = _validate_test_layout(
            {"convention": "python_pytest", "mode": "strict"}
        )
        self.assertTrue(any("mode" in e for e in errors), errors)

    def test_non_dict_layout_is_rejected(self) -> None:
        errors = _validate_test_layout("python_pytest")
        self.assertTrue(any("test_layout" in e for e in errors), errors)


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
