#!/usr/bin/env python3
"""Tests for smm_schema.json and smm_schema.py.

Covers the JSON Schema for the curated SMM document
(shared_mental_model.json) plus the Python validator mirroring
event_schema.validate_event().

Entry-type-specific validators live in test_smm_schema_entries.py.
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

_VALID_ID = "1a2b3c4d5e6f"
_VALID_ID_2 = "aabbccddeeff"
_VALID_TS = "2026-04-09T02:15:28.155493+00:00"


def _entry(id_=_VALID_ID, content="test", source="seed", ts=_VALID_TS, **extra):
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

    def test_content_maxlength_matches_python(self):
        """Per-pillar maxLength in JSON schema must match constant."""
        defs = self.schema["$defs"]
        pillar_to_def = {
            "intent": "intent_entry",
            "constraints": "constraint_entry",
            "risks": "risk_entry",
            "wisdom": "wisdom_entry",
        }
        for pillar, def_name in pillar_to_def.items():
            expected = smm_schema.PILLAR_CONTENT_MAX_LENGTH[pillar]
            entry_def = defs[def_name]
            content_props = entry_def["allOf"][1]["properties"]["content"]
            self.assertEqual(
                content_props["maxLength"],
                expected,
                f"{pillar} maxLength mismatch:"
                f" JSON={content_props.get('maxLength')}"
                f" vs Python={expected}",
            )


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

    def test_entry_id_must_be_12_char_hex(self):
        e = _entry(id_="zzzzzzzzzzzz")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("id" in err for err in errors))

    def test_entry_id_short_rejected(self):
        e = _entry(id_="abcdef")
        errors = smm_schema.validate_smm(_smm(intent=[e]))
        self.assertTrue(any("id" in err for err in errors))

    def test_entry_id_old_uuid_rejected(self):
        e = _entry(id_="11111111-2222-4333-8444-555555555555")
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
        e = _entry(
            source="event",
            type="goal",
            source_event_id=_VALID_ID_2,
        )
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


class TestEventIdRe(unittest.TestCase):
    """EVENT_ID_RE is THE id pattern — event_schema (metadata.resolves),
    system_context (source_event_id), and execution_plan (milestone.schedules)
    all validate against it, then consume the id by exact string equality.
    """

    def test_accepts_bare_12_hex(self):
        self.assertTrue(smm_schema.EVENT_ID_RE.match(_VALID_ID))

    def test_rejects_trailing_newline(self):
        """Anchored with `\\Z`, not `$` — `$` also matches BEFORE a trailing
        newline, so it accepted "1a2b3c4d5e6f\\n" as valid. Such an id passes
        validation and then equals no real id, silently resolving/scheduling
        nothing.
        """
        self.assertIsNone(smm_schema.EVENT_ID_RE.match(_VALID_ID + "\n"))

    def test_rejects_wrong_length_and_non_hex(self):
        for bad in ("1a2b3c4d5e6", "1a2b3c4d5e6ff", "1A2B3C4D5E6F", "not-an-id", ""):
            with self.subTest(bad=bad):
                self.assertIsNone(smm_schema.EVENT_ID_RE.match(bad))


if __name__ == "__main__":
    unittest.main()
