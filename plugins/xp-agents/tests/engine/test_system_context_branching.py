#!/usr/bin/env python3
"""Tests for branching_strategy validation in system_context_schema.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from system_context_schema import validate_system_context


def _valid_doc(**overrides: object) -> dict:
    """Return a minimal valid system context document with optional overrides."""
    doc = {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }
    doc.update(overrides)
    return doc


class TestBranchingStrategyValidation(unittest.TestCase):
    """Validate the optional branching_strategy field in system_context.json."""

    def test_valid_without_branching_strategy(self) -> None:
        doc = _valid_doc()
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_branching_strategy_minimal(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_branching_strategy_full(self) -> None:
        doc = _valid_doc(
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
        doc = _valid_doc(branching_strategy={"stage": 0})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_valid_stage_three(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 3})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_stage_negative(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": -1})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_over_3(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 4})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_non_int(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": "high"})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_invalid_stage_bool(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": True})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_missing_stage_field(self) -> None:
        doc = _valid_doc(branching_strategy={"user_namespace": "paul"})
        errors = validate_system_context(doc)
        self.assertTrue(any("stage" in e for e in errors))

    def test_branching_strategy_not_dict(self) -> None:
        doc = _valid_doc(branching_strategy="stage-1")
        errors = validate_system_context(doc)
        self.assertTrue(any("branching_strategy" in e for e in errors))

    def test_invalid_user_namespace_type(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "user_namespace": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("user_namespace" in e for e in errors))

    def test_invalid_protected_branches_type(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "protected_branches": "main"})
        errors = validate_system_context(doc)
        self.assertTrue(any("protected_branches" in e for e in errors))

    def test_empty_protected_branches_valid(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "protected_branches": []})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_protected_branches_item_type(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "protected_branches": [123]})
        errors = validate_system_context(doc)
        self.assertTrue(any("protected_branches" in e for e in errors))

    def test_invalid_integration_branch_type(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "integration_branch": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("integration_branch" in e for e in errors))

    def test_integration_branch_null_is_valid(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "integration_branch": None})
        errors = validate_system_context(doc)
        self.assertEqual(errors, [])

    def test_invalid_rationale_type(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "rationale": 42})
        errors = validate_system_context(doc)
        self.assertTrue(any("rationale" in e for e in errors))

    def test_rationale_budget_enforcement(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "rationale": "x" * 301})
        errors = validate_system_context(doc)
        self.assertTrue(any("budget" in e.lower() or "rationale" in e for e in errors))

    def test_rationale_budget_skipped_when_not_enforced(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "rationale": "x" * 301})
        errors = validate_system_context(doc, enforce_budget=False)
        self.assertEqual(errors, [])

    def test_user_namespace_budget_enforcement(self) -> None:
        doc = _valid_doc(branching_strategy={"stage": 1, "user_namespace": "x" * 51})
        errors = validate_system_context(doc)
        self.assertTrue(
            any("budget" in e.lower() or "user_namespace" in e for e in errors)
        )


if __name__ == "__main__":
    unittest.main()
