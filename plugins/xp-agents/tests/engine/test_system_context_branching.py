#!/usr/bin/env python3
"""Tests for branching_strategy validation in system_context_schema.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from system_context_schema import validate_system_context


class TestBranchingStrategyValidation(unittest.TestCase):
    """Validate the optional branching_strategy field in system_context.json."""

    def test_valid_without_branching_strategy(self) -> None:
        doc = valid_doc()
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_branching_strategy_minimal(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_branching_strategy_full(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 2,
                "user_namespace": "paul",
                "protected_branches": ["main"],
                "integration_branch": "develop",
                "rationale": "Team project with CI",
            }
        )
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_stage_zero(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 0})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_stage_three(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 3})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_stage_negative(self) -> None:
        doc = valid_doc(branching_strategy={"stage": -1})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_over_3(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 4})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_non_int(self) -> None:
        doc = valid_doc(branching_strategy={"stage": "high"})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_bool(self) -> None:
        doc = valid_doc(branching_strategy={"stage": True})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_missing_stage_field(self) -> None:
        doc = valid_doc(branching_strategy={"user_namespace": "paul"})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_branching_strategy_not_dict(self) -> None:
        doc = valid_doc(branching_strategy="stage-1")
        errors = validate_system_context(doc)
        self.assertTrue(any("branching_strategy" in e for e in errors))

    def test_invalid_user_namespace_type(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "user_namespace": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("user_namespace" in e for e in errors))

    def test_invalid_protected_branches_type(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "protected_branches": "main"})
        errors = validate_system_context(doc)
        self.assertTrue(any("protected_branches" in e for e in errors))

    def test_empty_protected_branches_valid(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "protected_branches": []})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_protected_branches_item_type(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "protected_branches": [123]})
        errors = validate_system_context(doc)
        self.assertTrue(any("protected_branches" in e for e in errors))

    def test_invalid_integration_branch_type(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "integration_branch": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("integration_branch" in e for e in errors))

    def test_integration_branch_null_is_valid(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "integration_branch": None})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_rationale_type(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "rationale": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("rationale" in e for e in errors))

    def test_rationale_budget_enforcement(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "rationale": "x" * 301})
        errors = validate_system_context(doc)
        self.assertTrue(any("budget" in e.lower() or "rationale" in e for e in errors))

    def test_rationale_budget_skipped_when_not_enforced(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "rationale": "x" * 301})
        errors = validate_system_context(doc, enforce_budget=False)
        self.assertEqual(errors, [])

    def test_user_namespace_budget_enforcement(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 1, "user_namespace": "x" * 51})
        errors = validate_system_context(doc)
        self.assertTrue(
            any("budget" in e.lower() or "user_namespace" in e for e in errors)
        )


class TestStagePromptDismissedAt(unittest.TestCase):
    """Optional ISO timestamp recording when the user dismissed the
    Stage 2 floor migration prompt at xp-kickoff Step 2.4. Sticky
    dismissal: when present (non-null) the prompt skips firing on
    subsequent kickoffs.
    """

    def test_valid_iso_timestamp_accepted(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "stage_prompt_dismissed_at": "2026-05-04T17:30:00+00:00",
            }
        )
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_field_absent_accepted(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 0})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_field_null_accepted(self) -> None:
        doc = valid_doc(
            branching_strategy={"stage": 0, "stage_prompt_dismissed_at": None}
        )
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_non_string_value_rejected(self) -> None:
        doc = valid_doc(
            branching_strategy={"stage": 0, "stage_prompt_dismissed_at": 12345}
        )
        errors = validate_system_context(doc)
        self.assertTrue(
            any("stage_prompt_dismissed_at" in e for e in errors),
            f"Expected error naming the field; got: {errors}",
        )

    def test_over_budget_string_rejected(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "stage_prompt_dismissed_at": "x" * 100,
            }
        )
        errors = validate_system_context(doc)
        self.assertTrue(
            any(
                "stage_prompt_dismissed_at" in e and "budget" in e.lower()
                for e in errors
            ),
            f"Expected over-budget error; got: {errors}",
        )

    def test_non_iso_string_rejected(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "stage_prompt_dismissed_at": "not a timestamp",
            }
        )
        errors = validate_system_context(doc)
        self.assertTrue(
            any("stage_prompt_dismissed_at" in e and "ISO" in e for e in errors),
            f"Expected ISO-format error; got: {errors}",
        )


if __name__ == "__main__":
    unittest.main()
