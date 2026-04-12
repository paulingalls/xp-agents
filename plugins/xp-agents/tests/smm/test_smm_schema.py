#!/usr/bin/env python3
"""Tests for smm_schema.json and smm_schema.py.

Covers the JSON Schema for the curated SMM document
(shared_mental_model.json) plus the Python validator mirroring
event_schema.validate_event().
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import smm_schema
from conftest import _PLUGIN_ROOT

# ---------------------------------------------------------------------------
# Helpers for building valid test fixtures
# ---------------------------------------------------------------------------

_VALID_UUID = "11111111-2222-4333-8444-555555555555"
_VALID_UUID_2 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_VALID_UUID_3 = "12345678-9abc-4def-8012-3456789abcde"
_VALID_TS = "2026-04-09T02:15:28.155493+00:00"


def _entry(id_=_VALID_UUID, content="test", source="seed", ts=_VALID_TS, **extra):
    """Build a valid base entry with overrides."""
    e = {"id": id_, "content": content, "source": source, "ts": ts}
    e.update(extra)
    return e


def _smm(intent=None, constraints=None, risks=None, wisdom=None):
    """Build a valid empty-ish SMM with overrides."""
    return {
        "intent": intent or [],
        "constraints": constraints or [],
        "risks": risks or [],
        "wisdom": wisdom or [],
    }


# ---------------------------------------------------------------------------
# Schema file tests
# ---------------------------------------------------------------------------


class TestSMMSchemaFile(unittest.TestCase):
    """Validate smm_schema.json is a well-formed JSON Schema."""

    @classmethod
    def setUpClass(cls):
        schema_path = _PLUGIN_ROOT / "smm" / "smm_schema.json"
        cls.schema_path = schema_path
        with open(schema_path) as f:
            cls.schema = json.load(f)

    def test_schema_file_exists(self):
        self.assertTrue(self.schema_path.exists())

    def test_schema_is_valid_json(self):
        self.assertIsInstance(self.schema, dict)

    def test_schema_declares_draft_07(self):
        self.assertIn("$schema", self.schema)
        self.assertIn("draft-07", self.schema["$schema"])

    def test_schema_requires_four_pillars(self):
        required = self.schema.get("required", [])
        self.assertIn("intent", required)
        self.assertIn("constraints", required)
        self.assertIn("risks", required)
        self.assertIn("wisdom", required)

    def test_schema_has_properties_for_four_pillars(self):
        props = self.schema.get("properties", {})
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertIn(pillar, props)
            self.assertEqual(props[pillar]["type"], "array")

    # --- Drift guards: JSON schema enums must match Python constants ---

    def test_source_enum_matches_python(self):
        defs = self.schema["$defs"]
        json_sources = set(defs["base_entry"]["properties"]["source"]["enum"])
        self.assertEqual(json_sources, set(smm_schema.VALID_SOURCES))

    def test_intent_type_enum_matches_python(self):
        defs = self.schema["$defs"]
        entry = defs["intent_entry"]["allOf"][1]
        json_types = set(entry["properties"]["type"]["enum"])
        self.assertEqual(json_types, set(smm_schema.VALID_INTENT_TYPES))

    def test_constraint_type_enum_matches_python(self):
        defs = self.schema["$defs"]
        entry = defs["constraint_entry"]["allOf"][1]
        json_types = set(entry["properties"]["type"]["enum"])
        self.assertEqual(json_types, set(smm_schema.VALID_CONSTRAINT_TYPES))

    def test_risk_type_enum_matches_python(self):
        defs = self.schema["$defs"]
        entry = defs["risk_entry"]["allOf"][1]
        json_types = set(entry["properties"]["type"]["enum"])
        self.assertEqual(json_types, set(smm_schema.VALID_RISK_TYPES))

    def test_risk_severity_enum_matches_python(self):
        defs = self.schema["$defs"]
        entry = defs["risk_entry"]["allOf"][1]
        json_severities = set(entry["properties"]["severity"]["enum"])
        self.assertEqual(json_severities, set(smm_schema.VALID_RISK_SEVERITIES))


# ---------------------------------------------------------------------------
# empty_smm() factory
# ---------------------------------------------------------------------------


class TestEmptySMM(unittest.TestCase):
    """empty_smm() returns a canonical empty document."""

    def test_returns_dict(self):
        self.assertIsInstance(smm_schema.empty_smm(), dict)

    def test_has_all_four_pillars(self):
        empty = smm_schema.empty_smm()
        self.assertEqual(empty["intent"], [])
        self.assertEqual(empty["constraints"], [])
        self.assertEqual(empty["risks"], [])
        self.assertEqual(empty["wisdom"], [])

    def test_empty_smm_is_valid(self):
        self.assertEqual(smm_schema.validate_smm(smm_schema.empty_smm()), [])


# ---------------------------------------------------------------------------
# Top-level document validation
# ---------------------------------------------------------------------------


class TestValidateSMMTopLevel(unittest.TestCase):
    """validate_smm rejects malformed top-level documents."""

    def test_valid_empty_smm_passes(self):
        self.assertEqual(smm_schema.validate_smm(_smm()), [])

    def test_non_dict_rejected(self):
        errors = smm_schema.validate_smm([])
        self.assertEqual(errors, ["SMM document must be an object"])

    def test_missing_intent_rejected(self):
        bad = _smm()
        del bad["intent"]
        errors = smm_schema.validate_smm(bad)
        self.assertIn("Missing required pillar: intent", errors)

    def test_missing_constraints_rejected(self):
        bad = _smm()
        del bad["constraints"]
        errors = smm_schema.validate_smm(bad)
        self.assertIn("Missing required pillar: constraints", errors)

    def test_missing_risks_rejected(self):
        bad = _smm()
        del bad["risks"]
        errors = smm_schema.validate_smm(bad)
        self.assertIn("Missing required pillar: risks", errors)

    def test_missing_wisdom_rejected(self):
        bad = _smm()
        del bad["wisdom"]
        errors = smm_schema.validate_smm(bad)
        self.assertIn("Missing required pillar: wisdom", errors)

    def test_pillar_must_be_list(self):
        bad = _smm()
        bad["intent"] = "not a list"
        errors = smm_schema.validate_smm(bad)
        self.assertIn("Pillar 'intent' must be an array", errors)


# ---------------------------------------------------------------------------
# Per-entry base field validation
# ---------------------------------------------------------------------------


class TestValidateSMMEntryBase(unittest.TestCase):
    """Every pillar entry must have id, content, source, ts."""

    def test_entry_missing_id_rejected(self):
        e = _entry()
        del e["id"]
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("id" in err for err in errors))

    def test_entry_missing_content_rejected(self):
        e = _entry()
        del e["content"]
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("content" in err for err in errors))

    def test_entry_missing_source_rejected(self):
        e = _entry()
        del e["source"]
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("source" in err for err in errors))

    def test_entry_missing_ts_rejected(self):
        e = _entry()
        del e["ts"]
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("ts" in err for err in errors))

    def test_entry_id_must_be_uuid4(self):
        # uuid v1-style string (no '4' in the version slot)
        e = _entry(id_="11111111-2222-1333-8444-555555555555")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("id" in err for err in errors))

    def test_entry_id_short_rejected(self):
        e = _entry(id_="not-a-uuid")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("id" in err for err in errors))

    def test_entry_source_enum(self):
        e = _entry(source="invented")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("source" in err for err in errors))

    def test_source_seed_valid(self):
        e = _entry(source="seed", type="goal")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_source_event_valid(self):
        e = _entry(source="event", type="goal", source_event_id=_VALID_UUID_2)
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_source_curated_valid(self):
        e = _entry(source="curated", type="goal")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_ts_must_be_iso8601(self):
        e = _entry(ts="not-a-date")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("ts" in err for err in errors))

    def test_source_event_id_optional(self):
        # Omitting source_event_id is fine.
        e = _entry(type="goal")
        self.assertEqual(smm_schema.validate_smm(_smm(intent=[e])), [])

    def test_source_event_id_must_be_uuid4_when_present(self):
        e = _entry(type="goal", source_event_id="bogus")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("source_event_id" in err for err in errors))


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
    """Constraint entries carry type: decision | convention, optional topic."""

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
    """Risk entries carry type (concern/assumption/debt/question) and severity."""

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


class TestValidateSMMCrossPillarIDs(unittest.TestCase):
    """IDs must be unique across every pillar."""

    def test_unique_ids_across_pillars_valid(self):
        smm = _smm(
            intent=[_entry(id_=_VALID_UUID, type="goal")],
            constraints=[_entry(id_=_VALID_UUID_2, type="convention")],
            risks=[_entry(id_=_VALID_UUID_3, type="concern", severity="problem")],
        )
        self.assertEqual(smm_schema.validate_smm(smm), [])

    def test_duplicate_ids_across_pillars_rejected(self):
        dup = _VALID_UUID
        smm = _smm(
            intent=[_entry(id_=dup, type="goal")],
            risks=[_entry(id_=dup, type="concern", severity="problem")],
        )
        errors = smm_schema.validate_smm(smm)
        self.assertTrue(
            any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)
        )

    def test_duplicate_ids_within_pillar_rejected(self):
        dup = _VALID_UUID
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
    """smm_schema.py exports pillar / source / severity / type constants."""

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
    """validate_entry validates a single entry against its pillar spec."""

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


if __name__ == "__main__":
    unittest.main()
