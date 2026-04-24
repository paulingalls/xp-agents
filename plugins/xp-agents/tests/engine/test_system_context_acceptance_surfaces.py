#!/usr/bin/env python3
"""Tests for acceptance_surfaces validation in system_context_schema.py.

Split from test_system_context_schema.py to keep files under 500 lines.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from system_context_schema import validate_system_context


def _valid_doc() -> dict:
    """Return a minimal valid system context document."""
    return {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }


class TestAcceptanceSurfaceValidation(unittest.TestCase):
    """Validation of optional acceptance_surfaces field."""

    def _surface(self, **overrides: object) -> dict:
        base: dict = {
            "name": "browser",
            "signals": ["Next.js in package.json"],
            "status": "covered",
        }
        base.update(overrides)
        return base

    def test_valid_entry(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface()]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_with_optional_harness(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(harness="playwright")]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_absent_field_valid(self) -> None:
        doc = _valid_doc()
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_empty_list_valid(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = []
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_empty_signals_valid(self) -> None:
        """Empty signals list is valid."""
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(signals=[])]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_missing_required_name(self) -> None:
        doc = _valid_doc()
        s = self._surface()
        del s["name"]
        doc["acceptance_surfaces"] = [s]
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e for e in errors))

    def test_missing_required_signals(self) -> None:
        doc = _valid_doc()
        s = self._surface()
        del s["signals"]
        doc["acceptance_surfaces"] = [s]
        errors = validate_system_context(doc)
        self.assertTrue(any("signals" in e for e in errors))

    def test_missing_required_status(self) -> None:
        doc = _valid_doc()
        s = self._surface()
        del s["status"]
        doc["acceptance_surfaces"] = [s]
        errors = validate_system_context(doc)
        self.assertTrue(any("status" in e for e in errors))

    def test_invalid_status_value(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(status="unknown")]
        errors = validate_system_context(doc)
        self.assertTrue(any("status" in e for e in errors))

    def test_signals_must_be_list(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(signals="not a list")]
        errors = validate_system_context(doc)
        self.assertTrue(any("signals" in e for e in errors))

    def test_signals_items_must_be_strings(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(signals=[123])]
        errors = validate_system_context(doc)
        self.assertTrue(any("signals" in e for e in errors))

    def test_name_must_be_string(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(name=42)]
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e for e in errors))

    def test_harness_must_be_string(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [self._surface(harness=123)]
        errors = validate_system_context(doc)
        self.assertTrue(any("harness" in e for e in errors))

    def test_not_a_list_rejected(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = "not a list"
        errors = validate_system_context(doc)
        self.assertTrue(any("acceptance_surfaces" in e for e in errors))

    def test_entry_not_dict_rejected(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = ["not a dict"]
        errors = validate_system_context(doc)
        self.assertTrue(any("acceptance_surfaces" in e for e in errors))

    def test_multiple_valid_surfaces(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [
            self._surface(name="browser", status="covered"),
            self._surface(name="cli", status="gap", harness="bats"),
        ]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_duplicate_names_rejected(self) -> None:
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [
            self._surface(name="browser", status="covered"),
            self._surface(name="browser", status="gap"),
        ]
        errors = validate_system_context(doc)
        self.assertTrue(any("duplicate name" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
