#!/usr/bin/env python3
"""Tests for smm_schema.py: per-pillar entry validation, constants, maxLength.

Split from test_smm_schema.py -- entry-type-specific validators and constants.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import smm_schema
from test_smm_schema import _entry, _smm

# ---------------------------------------------------------------------------
# Pillar-specific field validation
# ---------------------------------------------------------------------------


class TestValidateSMMIntentEntry(unittest.TestCase):
    """Intent entries carry type: goal | customer_intent."""

    def test_intent_type_goal_valid(self):
        e = _entry(type="goal")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_intent_type_customer_intent_valid(self):
        e = _entry(type="customer_intent")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_intent_type_bogus_rejected(self):
        e = _entry(type="nonsense")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("type" in err for err in errors))


class TestValidateSMMConstraintEntry(unittest.TestCase):
    """Constraint entries carry type: decision | convention."""

    def test_constraint_type_decision_valid(self):
        e = _entry(type="decision", topic="auth")
        self.assertEqual(smm_schema.validate_smm(_smm(constraints=[e])), [])

    def test_constraint_type_convention_valid(self):
        e = _entry(type="convention")
        self.assertEqual(smm_schema.validate_smm(_smm(constraints=[e])), [])

    def test_constraint_topic_optional(self):
        e = _entry(type="decision")
        self.assertEqual(smm_schema.validate_smm(_smm(constraints=[e])), [])

    def test_constraint_topic_must_be_string(self):
        e = _entry(type="decision", topic=42)
        errors = smm_schema.validate_smm(_smm(constraints=[e]))
        self.assertTrue(any("topic" in err for err in errors))

    def test_constraint_type_bogus_rejected(self):
        e = _entry(type="nonsense")
        errors = smm_schema.validate_smm(_smm(constraints=[e]))
        self.assertTrue(any("type" in err for err in errors))


class TestValidateSMMRiskEntry(unittest.TestCase):
    """Risk entries: concern/assumption/debt/question + severity."""

    def test_risk_type_concern_severity_problem_valid(self):
        e = _entry(type="concern", severity="problem")
        self.assertEqual(smm_schema.validate_smm(_smm(risks=[e])), [])

    def test_risk_type_assumption_severity_uncertainty_valid(self):
        e = _entry(type="assumption", severity="uncertainty")
        self.assertEqual(smm_schema.validate_smm(_smm(risks=[e])), [])

    def test_risk_type_debt_severity_debt_valid(self):
        e = _entry(type="debt", severity="debt")
        self.assertEqual(smm_schema.validate_smm(_smm(risks=[e])), [])

    def test_risk_type_question_valid(self):
        e = _entry(type="question", severity="uncertainty")
        self.assertEqual(smm_schema.validate_smm(_smm(risks=[e])), [])

    def test_risk_severity_bogus_rejected(self):
        e = _entry(type="concern", severity="mild")
        errors = smm_schema.validate_smm(_smm(risks=[e]))
        self.assertTrue(any("severity" in err for err in errors))

    def test_risk_type_bogus_rejected(self):
        e = _entry(type="hazard", severity="problem")
        errors = smm_schema.validate_smm(_smm(risks=[e]))
        self.assertTrue(any("type" in err for err in errors))


class TestValidateSMMWisdomEntry(unittest.TestCase):
    """Wisdom entries only need the base fields."""

    def test_wisdom_base_valid(self):
        e = _entry()
        self.assertEqual(smm_schema.validate_smm(_smm(wisdom=[e])), [])

    def test_wisdom_accepts_seed_source(self):
        e = _entry(source="seed")
        self.assertEqual(smm_schema.validate_smm(_smm(wisdom=[e])), [])


# ---------------------------------------------------------------------------
# Cross-pillar ID uniqueness
# ---------------------------------------------------------------------------

_VALID_ID = "1a2b3c4d5e6f"
_VALID_ID_2 = "aabbccddeeff"
_VALID_ID_3 = "123456789abc"


class TestValidateSMMCrossPillarIDs(unittest.TestCase):
    """IDs must be unique across every pillar."""

    def test_unique_ids_across_pillars_valid(self):
        smm = _smm(
            intent=[_entry(id_=_VALID_ID, type="goal")],
            constraints=[_entry(id_=_VALID_ID_2, type="convention")],
            risks=[
                _entry(
                    id_=_VALID_ID_3,
                    type="concern",
                    severity="problem",
                )
            ],
        )
        self.assertEqual(smm_schema.validate_smm(smm), [])

    def test_duplicate_ids_across_pillars_rejected(self):
        dup = _VALID_ID
        smm = _smm(
            intent=[_entry(id_=dup, type="goal")],
            risks=[_entry(id_=dup, type="concern", severity="problem")],
        )
        errors = smm_schema.validate_smm(smm)
        self.assertTrue(
            any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)
        )

    def test_duplicate_ids_within_pillar_rejected(self):
        dup = _VALID_ID
        smm = _smm(
            intent=[
                _entry(id_=dup, type="goal"),
                _entry(id_=dup, type="goal", content="second"),
            ]
        )
        errors = smm_schema.validate_smm(smm)
        self.assertTrue(
            any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)
        )


# ---------------------------------------------------------------------------
# Constants exported
# ---------------------------------------------------------------------------


class TestSMMSchemaConstants(unittest.TestCase):
    """smm_schema.py exports pillar/source/severity/type constants."""

    def test_pillar_constants(self):
        self.assertEqual(smm_schema.PILLAR_INTENT, "intent")
        self.assertEqual(smm_schema.PILLAR_CONSTRAINTS, "constraints")
        self.assertEqual(smm_schema.PILLAR_RISKS, "risks")
        self.assertEqual(smm_schema.PILLAR_WISDOM, "wisdom")

    def test_source_constants(self):
        self.assertEqual(smm_schema.SOURCE_SEED, "seed")
        self.assertEqual(smm_schema.SOURCE_EVENT, "event")
        self.assertEqual(smm_schema.SOURCE_CURATED, "curated")

    def test_valid_sources_frozenset(self):
        self.assertIsInstance(smm_schema.VALID_SOURCES, frozenset)
        self.assertEqual(
            smm_schema.VALID_SOURCES,
            frozenset({"seed", "event", "curated"}),
        )

    def test_valid_risk_severities(self):
        self.assertEqual(
            smm_schema.VALID_RISK_SEVERITIES,
            frozenset({"problem", "uncertainty", "debt"}),
        )

    def test_valid_intent_types(self):
        self.assertEqual(
            smm_schema.VALID_INTENT_TYPES,
            frozenset({"goal", "customer_intent"}),
        )

    def test_valid_constraint_types(self):
        self.assertEqual(
            smm_schema.VALID_CONSTRAINT_TYPES,
            frozenset({"decision", "convention"}),
        )

    def test_valid_risk_types(self):
        self.assertEqual(
            smm_schema.VALID_RISK_TYPES,
            frozenset({"concern", "assumption", "debt", "question"}),
        )


# ---------------------------------------------------------------------------
# Per-entry validation (validate_entry)
# ---------------------------------------------------------------------------


class TestValidateEntry(unittest.TestCase):
    """validate_entry validates a single entry against pillar spec."""

    def test_valid_intent_entry_returns_empty(self):
        e = _entry(type="goal")
        self.assertEqual(smm_schema.validate_entry(e, "intent"), [])

    def test_valid_constraint_entry_with_topic(self):
        e = _entry(type="decision", topic="auth-method")
        self.assertEqual(smm_schema.validate_entry(e, "constraints"), [])

    def test_valid_risk_entry_with_severity(self):
        e = _entry(type="concern", severity="problem")
        self.assertEqual(smm_schema.validate_entry(e, "risks"), [])

    def test_valid_wisdom_entry(self):
        e = _entry()
        self.assertEqual(smm_schema.validate_entry(e, "wisdom"), [])

    def test_missing_content_returns_errors(self):
        e = _entry()
        del e["content"]
        errors = smm_schema.validate_entry(e, "wisdom")
        self.assertTrue(any("content" in err for err in errors))

    def test_missing_id_returns_errors(self):
        e = _entry()
        del e["id"]
        errors = smm_schema.validate_entry(e, "wisdom")
        self.assertTrue(any("id" in err for err in errors))

    def test_invalid_pillar_name_returns_error(self):
        e = _entry()
        errors = smm_schema.validate_entry(e, "bogus")
        self.assertEqual(len(errors), 1)
        self.assertIn("bogus", errors[0])

    def test_invalid_type_for_pillar_returns_error(self):
        e = _entry(type="concern")
        errors = smm_schema.validate_entry(e, "intent")
        self.assertTrue(any("type" in err for err in errors))

    def test_invalid_severity_returns_error(self):
        e = _entry(type="concern", severity="mild")
        errors = smm_schema.validate_entry(e, "risks")
        self.assertTrue(any("severity" in err for err in errors))

    def test_non_dict_returns_error(self):
        errors = smm_schema.validate_entry("not a dict", "intent")
        self.assertTrue(len(errors) > 0)

    def test_source_event_id_validated(self):
        e = _entry(type="goal", source_event_id="not-a-uuid")
        errors = smm_schema.validate_entry(e, "intent")
        self.assertTrue(any("source_event_id" in err for err in errors))


# ---------------------------------------------------------------------------
# Per-pillar content maxLength
# ---------------------------------------------------------------------------


class TestPillarContentMaxLength(unittest.TestCase):
    """PILLAR_CONTENT_MAX_LENGTH enforces per-pillar content budgets."""

    def test_constant_exists_with_correct_values(self):
        expected = {
            "intent": 200,
            "constraints": 150,
            "risks": 200,
            "wisdom": 150,
        }
        self.assertEqual(smm_schema.PILLAR_CONTENT_MAX_LENGTH, expected)

    def test_validate_entry_rejects_over_budget_intent(self):
        e = _entry(content="x" * 201, type="goal")
        errors = smm_schema.validate_entry(e, "intent")
        self.assertTrue(any("201" in err and "200" in err for err in errors))

    def test_validate_entry_rejects_over_budget_constraints(self):
        e = _entry(content="x" * 151, type="convention")
        errors = smm_schema.validate_entry(e, "constraints")
        self.assertTrue(any("151" in err and "150" in err for err in errors))

    def test_validate_entry_rejects_over_budget_risks(self):
        e = _entry(content="x" * 201, type="concern", severity="problem")
        errors = smm_schema.validate_entry(e, "risks")
        self.assertTrue(any("201" in err and "200" in err for err in errors))

    def test_validate_entry_rejects_over_budget_wisdom(self):
        e = _entry(content="x" * 151)
        errors = smm_schema.validate_entry(e, "wisdom")
        self.assertTrue(any("151" in err and "150" in err for err in errors))

    def test_validate_entry_accepts_at_budget_limit(self):
        e = _entry(content="x" * 200, type="goal")
        self.assertEqual(smm_schema.validate_entry(e, "intent"), [])

    def test_validate_entry_accepts_under_budget(self):
        e = _entry(content="short", type="goal")
        self.assertEqual(smm_schema.validate_entry(e, "intent"), [])

    def test_validate_smm_accepts_over_budget_entry(self):
        """validate_smm (read path) grandfathers over-budget entries."""
        e = _entry(content="x" * 201, type="goal")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])


if __name__ == "__main__":
    unittest.main()
