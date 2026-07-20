#!/usr/bin/env python3
"""Tests for system_context_schema.py: constants, base validity, budgets, stack.

Split from test_system_context_schema.py (over the 500-line cap); module/
convention/principle/project_specific/acceptance-surface/source-event-id/
count-cap validation live in the test_system_context_schema_fields.py
sibling.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from system_context_schema import (
    CONVENTION_MAXLENGTH,
    FIELD_MAXLENGTH,
    MODULE_FIELD_MAXLENGTH,
    PRINCIPLE_FIELD_MAXLENGTH,
    STACK_FIELD_MAXLENGTH,
    SYSTEM_CONTEXT_FILENAME,
    empty_system_context,
    validate_system_context,
)


class TestEmptySystemContext(unittest.TestCase):
    def test_empty_system_context_valid(self) -> None:
        doc = empty_system_context()
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_empty_system_context_has_all_fields(self) -> None:
        doc = empty_system_context()
        for field in (
            "product",
            "architecture_overview",
            "stack",
            "modules",
            "conventions",
            "principles",
            "project_specific",
        ):
            self.assertIn(field, doc)


class TestConstants(unittest.TestCase):
    def test_filename(self) -> None:
        self.assertEqual(SYSTEM_CONTEXT_FILENAME, "system_context.json")

    def test_field_budgets_present(self) -> None:
        self.assertIn("product", FIELD_MAXLENGTH)
        self.assertIn("architecture_overview", FIELD_MAXLENGTH)

    def test_stack_field_budget(self) -> None:
        self.assertIsInstance(STACK_FIELD_MAXLENGTH, int)
        self.assertGreater(STACK_FIELD_MAXLENGTH, 0)


class TestValidDocument(unittest.TestCase):
    def test_valid_full_document(self) -> None:
        doc = valid_doc()
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_with_optional_stack_fields(self) -> None:
        doc = valid_doc()
        doc["stack"]["runtime"] = "Python 3.10+"
        doc["stack"]["dependencies_policy"] = "stdlib only"
        doc["stack"]["package_manager"] = "none"
        doc["stack"]["test_command"] = "pytest -n auto"
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_test_command_validates_as_optional_string(self) -> None:
        # test_command joined the optional stack-field tuple in the
        # spike-008 follow-up. Pin its validation alongside the other
        # optional stack strings so a future schema change doesn't
        # silently let through (e.g.) a list value.
        doc = valid_doc()
        doc["stack"]["test_command"] = ["pytest", "-n", "auto"]
        errors = validate_system_context(doc)
        self.assertTrue(
            any("test_command must be a string" in e for e in errors),
            f"non-string test_command should fail validation; got {errors}",
        )

    def test_worktree_bootstrap_valid_as_optional_string(self) -> None:
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = "./scripts/init-worktree.sh"
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_worktree_bootstrap_must_be_a_string(self) -> None:
        # A single command string, not a list: the stack loop enforces
        # isinstance(str), and multi-step logic belongs in the project's
        # own script (version-controlled) rather than in the SMM pointer.
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = ["npm", "ci"]
        errors = validate_system_context(doc)
        self.assertTrue(
            any("worktree_bootstrap must be a string" in e for e in errors),
            f"non-string worktree_bootstrap should fail validation; got {errors}",
        )

    def test_worktree_bootstrap_over_budget(self) -> None:
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = "x" * (STACK_FIELD_MAXLENGTH + 1)
        errors = validate_system_context(doc)
        self.assertTrue(
            any("worktree_bootstrap" in e and "budget" in e for e in errors),
            f"over-budget worktree_bootstrap should fail validation; got {errors}",
        )

    def test_valid_with_optional_module_fields(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["file_count"] = 42
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_with_principle_optional_fields(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["rationale"] = "Industry standard"
        doc["principles"][0]["source_event_id"] = "abcdef012345"
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])


class TestMissingRequiredFields(unittest.TestCase):
    def test_not_a_dict(self) -> None:
        errors = validate_system_context("not a dict")
        self.assertTrue(any("object" in e for e in errors))

    def test_missing_each_required_field(self) -> None:
        required = [
            "product",
            "architecture_overview",
            "stack",
            "modules",
            "conventions",
            "principles",
            "project_specific",
        ]
        for field in required:
            doc = valid_doc()
            del doc[field]
            errors = validate_system_context(doc)
            self.assertTrue(
                any(field in e for e in errors),
                f"Expected error mentioning {field!r}, got {errors}",
            )


class TestFieldBudgets(unittest.TestCase):
    def test_product_within_budget(self) -> None:
        doc = valid_doc()
        doc["product"] = "x" * FIELD_MAXLENGTH["product"]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_product_over_budget(self) -> None:
        doc = valid_doc()
        doc["product"] = "x" * (FIELD_MAXLENGTH["product"] + 1)
        errors = validate_system_context(doc)
        self.assertTrue(any("product" in e and "budget" in e for e in errors))

    def test_architecture_overview_over_budget(self) -> None:
        doc = valid_doc()
        doc["architecture_overview"] = "x" * (
            FIELD_MAXLENGTH["architecture_overview"] + 1
        )
        errors = validate_system_context(doc)
        self.assertTrue(
            any("architecture_overview" in e and "budget" in e for e in errors)
        )

    def test_enforce_budget_false_skips_budgets(self) -> None:
        doc = valid_doc()
        doc["product"] = "x" * (FIELD_MAXLENGTH["product"] + 100)
        doc["architecture_overview"] = "x" * (
            FIELD_MAXLENGTH["architecture_overview"] + 100
        )
        doc["conventions"] = ["x" * (CONVENTION_MAXLENGTH + 100)]
        doc["modules"][0]["purpose"] = "x" * (MODULE_FIELD_MAXLENGTH["purpose"] + 100)
        doc["modules"][0]["name"] = "x" * 200
        doc["modules"][0]["path"] = "x" * 500
        doc["principles"][0]["decision"] = "x" * (
            PRINCIPLE_FIELD_MAXLENGTH["decision"] + 100
        )
        doc["principles"][0]["topic"] = "x" * 200
        doc["stack"]["languages"] = ["x" * 200]
        doc["project_specific"] = [{"name": "x" * 200, "content": "x" * 1000}]
        doc["acceptance_surfaces"] = [
            {
                "name": "x" * 200,
                "signals": ["x" * 500],
                "status": "covered",
                "harness": "x" * 200,
            }
        ]
        errors = validate_system_context(doc, enforce_budget=False)
        self.assertEqual(errors, [])


class TestStackValidation(unittest.TestCase):
    def test_stack_must_be_dict(self) -> None:
        doc = valid_doc()
        doc["stack"] = "not a dict"
        errors = validate_system_context(doc)
        self.assertTrue(any("stack" in e for e in errors))

    def test_languages_required(self) -> None:
        doc = valid_doc()
        doc["stack"] = {}
        errors = validate_system_context(doc)
        self.assertTrue(any("languages" in e for e in errors))

    def test_languages_must_be_list(self) -> None:
        doc = valid_doc()
        doc["stack"]["languages"] = "Python"
        errors = validate_system_context(doc)
        self.assertTrue(any("languages" in e for e in errors))

    def test_languages_items_must_be_strings(self) -> None:
        doc = valid_doc()
        doc["stack"]["languages"] = [42]
        errors = validate_system_context(doc)
        self.assertTrue(any("languages" in e for e in errors))

    def test_optional_stack_fields_must_be_strings(self) -> None:
        doc = valid_doc()
        doc["stack"]["runtime"] = 42
        errors = validate_system_context(doc)
        self.assertTrue(any("runtime" in e for e in errors))

    def test_optional_stack_field_over_budget(self) -> None:
        doc = valid_doc()
        doc["stack"]["runtime"] = "x" * (STACK_FIELD_MAXLENGTH + 1)
        errors = validate_system_context(doc)
        self.assertTrue(any("runtime" in e and "budget" in e for e in errors))

    def test_stack_language_item_over_budget(self) -> None:
        doc = valid_doc()
        doc["stack"]["languages"] = ["x" * 31]
        errors = validate_system_context(doc)
        self.assertTrue(any("languages" in e and "budget" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
