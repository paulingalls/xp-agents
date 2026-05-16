#!/usr/bin/env python3
"""Tests for system_context_schema.py — validation logic for system_context.json."""

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
    PROJECT_SPECIFIC_CONTENT_MAXLENGTH,
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


class TestModuleValidation(unittest.TestCase):
    def test_modules_must_be_list(self) -> None:
        doc = valid_doc()
        doc["modules"] = "not a list"
        errors = validate_system_context(doc)
        self.assertTrue(any("modules" in e for e in errors))

    def test_module_must_be_dict(self) -> None:
        doc = valid_doc()
        doc["modules"] = ["not a dict"]
        errors = validate_system_context(doc)
        self.assertTrue(any("modules" in e for e in errors))

    def test_module_missing_name(self) -> None:
        doc = valid_doc()
        del doc["modules"][0]["name"]
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e for e in errors))

    def test_module_missing_purpose(self) -> None:
        doc = valid_doc()
        del doc["modules"][0]["purpose"]
        errors = validate_system_context(doc)
        self.assertTrue(any("purpose" in e for e in errors))

    def test_module_missing_path(self) -> None:
        doc = valid_doc()
        del doc["modules"][0]["path"]
        errors = validate_system_context(doc)
        self.assertTrue(any("path" in e for e in errors))

    def test_module_purpose_over_budget(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["purpose"] = "x" * (MODULE_FIELD_MAXLENGTH["purpose"] + 1)
        errors = validate_system_context(doc)
        self.assertTrue(any("purpose" in e and "budget" in e for e in errors))

    def test_module_purpose_cap_tightened_to_100(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["purpose"] = "x" * 101
        errors = validate_system_context(doc)
        self.assertTrue(
            any("purpose" in e and "budget" in e for e in errors),
            f"100ch cap not enforced; got {errors}",
        )

    def test_module_name_over_budget(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["name"] = "x" * 51
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e and "budget" in e for e in errors))

    def test_module_path_over_budget(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["path"] = "x" * 201
        errors = validate_system_context(doc)
        self.assertTrue(any("path" in e and "budget" in e for e in errors))

    def test_module_file_count_must_be_int(self) -> None:
        doc = valid_doc()
        doc["modules"][0]["file_count"] = "many"
        errors = validate_system_context(doc)
        self.assertTrue(any("file_count" in e for e in errors))


class TestConventionValidation(unittest.TestCase):
    def test_conventions_must_be_list(self) -> None:
        doc = valid_doc()
        doc["conventions"] = "not a list"
        errors = validate_system_context(doc)
        self.assertTrue(any("conventions" in e for e in errors))

    def test_convention_must_be_string(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [42]
        errors = validate_system_context(doc)
        self.assertTrue(any("conventions" in e for e in errors))

    def test_convention_over_budget(self) -> None:
        doc = valid_doc()
        doc["conventions"] = ["x" * (CONVENTION_MAXLENGTH + 1)]
        errors = validate_system_context(doc)
        self.assertTrue(any("budget" in e for e in errors))


class TestPrincipleValidation(unittest.TestCase):
    def test_principles_must_be_list(self) -> None:
        doc = valid_doc()
        doc["principles"] = "not a list"
        errors = validate_system_context(doc)
        self.assertTrue(any("principles" in e for e in errors))

    def test_principle_must_be_dict(self) -> None:
        doc = valid_doc()
        doc["principles"] = ["not a dict"]
        errors = validate_system_context(doc)
        self.assertTrue(any("principles" in e for e in errors))

    def test_principle_missing_topic(self) -> None:
        doc = valid_doc()
        del doc["principles"][0]["topic"]
        errors = validate_system_context(doc)
        self.assertTrue(any("topic" in e for e in errors))

    def test_principle_missing_decision(self) -> None:
        doc = valid_doc()
        del doc["principles"][0]["decision"]
        errors = validate_system_context(doc)
        self.assertTrue(any("decision" in e for e in errors))

    def test_principle_decision_over_budget(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["decision"] = "x" * (
            PRINCIPLE_FIELD_MAXLENGTH["decision"] + 1
        )
        errors = validate_system_context(doc)
        self.assertTrue(any("decision" in e and "budget" in e for e in errors))

    def test_principle_rationale_over_budget(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["rationale"] = "x" * (
            PRINCIPLE_FIELD_MAXLENGTH["rationale"] + 1
        )
        errors = validate_system_context(doc)
        self.assertTrue(any("rationale" in e and "budget" in e for e in errors))

    def test_principle_topic_over_budget(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["topic"] = "x" * 61
        errors = validate_system_context(doc)
        self.assertTrue(any("topic" in e and "budget" in e for e in errors))

    def test_principle_source_event_id_valid(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = "abcdef012345"
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_principle_source_event_id_invalid(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = "not-hex"
        errors = validate_system_context(doc)
        self.assertTrue(any("source_event_id" in e for e in errors))


class TestProjectSpecificValidation(unittest.TestCase):
    def test_project_specific_must_be_list(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = "not a list"
        errors = validate_system_context(doc)
        self.assertTrue(any("project_specific" in e for e in errors))

    def test_project_specific_entry_must_be_dict(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = ["not a dict"]
        errors = validate_system_context(doc)
        self.assertTrue(any("project_specific" in e for e in errors))

    def test_project_specific_missing_name(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"content": "value"}]
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e for e in errors))

    def test_project_specific_missing_content(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "section"}]
        errors = validate_system_context(doc)
        self.assertTrue(any("content" in e for e in errors))

    def test_project_specific_name_over_budget(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "x" * 51, "content": "ok"}]
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e and "budget" in e for e in errors))

    def test_project_specific_content_over_budget_string(self) -> None:
        doc = valid_doc()
        # JSON serialization of a string adds 2 chars (the quotes), so a
        # cap-length string already serializes to cap+2.
        doc["project_specific"] = [
            {"name": "notes", "content": "x" * PROJECT_SPECIFIC_CONTENT_MAXLENGTH}
        ]
        errors = validate_system_context(doc)
        self.assertTrue(any("content" in e and "budget" in e for e in errors))

    def test_project_specific_content_over_budget_list(self) -> None:
        doc = valid_doc()
        # List of strings serializing to >500ch.
        doc["project_specific"] = [{"name": "items", "content": ["x" * 80] * 8}]
        errors = validate_system_context(doc)
        self.assertTrue(any("content" in e and "budget" in e for e in errors))

    def test_project_specific_duplicate_names(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [
            {"name": "hooks", "content": "Hook info"},
            {"name": "hooks", "content": "Duplicate"},
        ]
        errors = validate_system_context(doc)
        self.assertTrue(
            any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)
        )

    def test_project_specific_content_string(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "notes", "content": "Some notes"}]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_project_specific_content_list(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "items", "content": ["item1", "item2"]}]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_project_specific_content_dict(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "config", "content": {"key": "value"}}]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_project_specific_content_list_of_dicts(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [
            {
                "name": "hooks",
                "content": [
                    {"event": "PreToolUse", "action": "validate"},
                    {"event": "PostToolUse", "action": "record"},
                ],
            }
        ]
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])


def _surface(**overrides: object) -> dict:
    s = {"name": "cli", "signals": ["pytest -n auto"], "status": "covered"}
    s.update(overrides)
    return s


class TestAcceptanceSurfaceValidation(unittest.TestCase):
    def test_acceptance_surface_name_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(name="x" * 51)])
        errors = validate_system_context(doc)
        self.assertTrue(any("name" in e and "budget" in e for e in errors))

    def test_acceptance_surface_harness_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(harness="x" * 51)])
        errors = validate_system_context(doc)
        self.assertTrue(any("harness" in e and "budget" in e for e in errors))

    def test_acceptance_surface_signal_item_over_budget(self) -> None:
        doc = valid_doc(acceptance_surfaces=[_surface(signals=["x" * 101])])
        errors = validate_system_context(doc)
        self.assertTrue(any("signals" in e and "budget" in e for e in errors))


class TestSourceEventIdEdgeCases(unittest.TestCase):
    def test_uppercase_hex_rejected(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = "ABCDEF012345"
        errors = validate_system_context(doc)
        self.assertTrue(any("source_event_id" in e for e in errors))

    def test_11_char_hex_rejected(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = "abcdef01234"
        errors = validate_system_context(doc)
        self.assertTrue(any("source_event_id" in e for e in errors))

    def test_13_char_hex_rejected(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = "abcdef0123456"
        errors = validate_system_context(doc)
        self.assertTrue(any("source_event_id" in e for e in errors))

    def test_empty_string_rejected(self) -> None:
        doc = valid_doc()
        doc["principles"][0]["source_event_id"] = ""
        errors = validate_system_context(doc)
        self.assertTrue(any("source_event_id" in e for e in errors))


class TestPrinciplesRename(unittest.TestCase):
    def test_validate_requires_principles_field(self) -> None:
        doc = valid_doc()
        del doc["principles"]
        errors = validate_system_context(doc)
        self.assertIn("Missing required field: principles", errors)

    def test_validate_rejects_dict_with_only_key_decisions(self) -> None:
        doc = valid_doc()
        doc["key_decisions"] = doc.pop("principles")
        errors = validate_system_context(doc)
        self.assertIn("Missing required field: principles", errors)

    def test_validate_ignores_extra_sources_key(self) -> None:
        doc = valid_doc(sources=["legacy.md", "other.md"])
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])


class TestCountCaps(unittest.TestCase):
    def test_count_cap_pairs_are_ints_with_soft_lt_hard(self) -> None:
        import system_context_schema as schema

        pairs = [
            ("MODULES_SOFT_CAP", "MODULES_HARD_CAP", 10, 15),
            ("CONVENTIONS_SOFT_CAP", "CONVENTIONS_HARD_CAP", 20, 30),
            ("PRINCIPLES_SOFT_CAP", "PRINCIPLES_HARD_CAP", 15, 20),
            ("PROJECT_SPECIFIC_SOFT_CAP", "PROJECT_SPECIFIC_HARD_CAP", 10, 15),
            (
                "ACCEPTANCE_SURFACES_SOFT_CAP",
                "ACCEPTANCE_SURFACES_HARD_CAP",
                5,
                8,
            ),
        ]
        for soft_name, hard_name, soft_val, hard_val in pairs:
            soft = getattr(schema, soft_name)
            hard = getattr(schema, hard_name)
            self.assertEqual(soft, soft_val, soft_name)
            self.assertEqual(hard, hard_val, hard_name)
            self.assertLess(soft, hard, f"{soft_name} must be < {hard_name}")


if __name__ == "__main__":
    unittest.main()
