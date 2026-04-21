#!/usr/bin/env python3
"""Tests for retro_schema.py: K/F/T validation with budgets and Try cap."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import retro_schema


class TestRetroSchemaValidation(unittest.TestCase):
    """retro_schema.py should validate K/F/T structure with budgets and Try cap."""

    def test_valid_retro_passes(self):
        data = {
            "keep": [{"content": "Good TDD"}],
            "fix": [{"content": "Fix slow tests"}],
            "try": [{"content": "Try pairing"}],
        }
        self.assertEqual(retro_schema.validate_retro(data), [])

    def test_five_tries_rejected(self):
        data = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"Try {i}"} for i in range(5)],
        }
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("4" in e and "try" in e.lower() for e in errors))

    def test_over_budget_keep_rejected(self):
        data = {"keep": [{"content": "x" * 251}], "fix": [], "try": []}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("keep" in e and "250" in e for e in errors))

    def test_over_budget_fix_rejected(self):
        data = {"keep": [], "fix": [{"content": "x" * 301}], "try": []}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("fix" in e and "300" in e for e in errors))

    def test_over_budget_try_rejected(self):
        data = {"keep": [], "fix": [], "try": [{"content": "x" * 301}]}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("try" in e and "300" in e for e in errors))

    def test_over_budget_analysis_notes_rejected(self):
        data = {"keep": [], "fix": [], "try": [], "analysis_notes": "x" * 601}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("analysis_notes" in e and "600" in e for e in errors))

    def test_at_budget_passes(self):
        data = {
            "keep": [{"content": "x" * 250}],
            "fix": [{"content": "x" * 300}],
            "try": [{"content": "x" * 300}],
            "analysis_notes": "x" * 600,
        }
        self.assertEqual(retro_schema.validate_retro(data), [])

    def test_four_tries_at_cap_passes(self):
        data = {
            "keep": [],
            "fix": [],
            "try": [{"content": f"Try {i}"} for i in range(4)],
        }
        self.assertEqual(retro_schema.validate_retro(data), [])

    def test_non_list_section_rejected(self):
        data = {"keep": "not a list", "fix": [], "try": []}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("keep" in e and "array" in e for e in errors))

    def test_legacy_string_items_validated(self):
        data = {"keep": ["x" * 251], "fix": [], "try": []}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("keep" in e and "250" in e for e in errors))

    def test_missing_sections_pass(self):
        self.assertEqual(retro_schema.validate_retro({}), [])

    def test_non_dict_non_string_item_rejected(self):
        data = {"keep": [42], "fix": [], "try": []}
        errors = retro_schema.validate_retro(data)
        self.assertTrue(any("keep[0]" in e and "dict or string" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
