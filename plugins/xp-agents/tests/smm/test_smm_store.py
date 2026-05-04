#!/usr/bin/env python3
"""Tests for smm_store: load/save for shared_mental_model.json."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import smm_schema
import smm_store
from conftest import _SMMTestCase, make_event

# Explicit `from event_schema import EVENT_TYPE_*` so a future constant rename
# fails at test collection (NameError) instead of silently changing behavior.
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_CONVENTION,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_DISCOVERY,
    EVENT_TYPE_GOAL,
    EVENT_TYPE_STATUS,
)


def _minimal_smm(**overrides):
    """Build a minimal valid SMM dict."""
    base = smm_schema.empty_smm()
    base.update(overrides)
    return base


_VALID_ENTRY = {
    "id": "111122224333",
    "content": "TDD always",
    "source": "seed",
    "ts": "1970-01-01T00:00:00+00:00",
}


class _StoreTestCase(unittest.TestCase):
    """Base with temp SMM dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.smm_dir = Path(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# load_smm
# ---------------------------------------------------------------------------


class TestLoadSMM(_StoreTestCase):
    def test_missing_file_returns_empty(self):
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(result, smm_schema.empty_smm())

    def test_loads_valid_json(self):
        data = _minimal_smm(wisdom=[_VALID_ENTRY])
        (self.smm_dir / smm_store.SMM_FILENAME).write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(result, data)

    def test_corrupt_json_raises_valueerror(self):
        (self.smm_dir / smm_store.SMM_FILENAME).write_text(
            "{not json", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            smm_store.load_smm(self.smm_dir)

    def test_schema_invalid_json_raises_valueerror(self):
        # Valid JSON but missing required pillars
        (self.smm_dir / smm_store.SMM_FILENAME).write_text(
            json.dumps({"intent": []}), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            smm_store.load_smm(self.smm_dir)

    def test_symlink_raises_oserror(self):
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(smm_schema.empty_smm()), encoding="utf-8")
        link = self.smm_dir / smm_store.SMM_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            smm_store.load_smm(self.smm_dir)


# ---------------------------------------------------------------------------
# save_smm
# ---------------------------------------------------------------------------


class TestSaveSMM(_StoreTestCase):
    def test_writes_valid_json_atomically(self):
        data = _minimal_smm(
            constraints=[{**_VALID_ENTRY, "type": EVENT_TYPE_CONVENTION}]
        )
        smm_store.save_smm(self.smm_dir, data)
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(result, data)

    def test_validates_before_write(self):
        bad = {"intent": []}  # Missing other pillars
        with self.assertRaises(ValueError):
            smm_store.save_smm(self.smm_dir, bad)
        # File should not exist
        self.assertFalse((self.smm_dir / smm_store.SMM_FILENAME).exists())

    def test_preserves_existing_on_validation_failure(self):
        good = _minimal_smm()
        smm_store.save_smm(self.smm_dir, good)
        bad = {"broken": True}
        with self.assertRaises(ValueError):
            smm_store.save_smm(self.smm_dir, bad)
        # Original file intact
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(result, good)

    def test_file_permissions_0o600(self):
        smm_store.save_smm(self.smm_dir, _minimal_smm())
        path = self.smm_dir / smm_store.SMM_FILENAME
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_overwrites_existing(self):
        first = _minimal_smm()
        second = _minimal_smm(wisdom=[_VALID_ENTRY])
        smm_store.save_smm(self.smm_dir, first)
        smm_store.save_smm(self.smm_dir, second)
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(result, second)

    def test_symlink_at_target_raises_oserror(self):
        real = self.smm_dir / "real.json"
        real.write_text("{}", encoding="utf-8")
        link = self.smm_dir / smm_store.SMM_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            smm_store.save_smm(self.smm_dir, _minimal_smm())

    def test_roundtrip_preserves_all_fields(self):
        entry = {
            **_VALID_ENTRY,
            # Intent pillar "type" is governed by smm_schema.VALID_INTENT_TYPES,
            # not event_schema.VALID_TYPES. Bare literal is correct;
            # pin allowlists this file.
            "type": "goal",
            "source_event_id": "aaabbbcccddd",
        }
        data = _minimal_smm(intent=[entry])
        smm_store.save_smm(self.smm_dir, data)
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(
            result["intent"][0]["source_event_id"],
            entry["source_event_id"],
        )
        self.assertEqual(result["intent"][0]["type"], "goal")


# ---------------------------------------------------------------------------
# add_item
# ---------------------------------------------------------------------------


class TestAddItem(_StoreTestCase):
    def test_generates_id(self):
        uid = smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        self.assertRegex(uid, r"^[0-9a-f]{12}$")

    def test_appends_to_correct_pillar(self):
        smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)
        self.assertEqual(smm["wisdom"][0]["content"], "TDD always")
        self.assertEqual(len(smm["intent"]), 0)

    def test_sets_source_and_timestamp(self):
        smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["wisdom"][0]
        self.assertEqual(entry["source"], "curated")
        self.assertIn("T", entry["ts"])
        self.assertIn("+", entry["ts"])

    def test_validates_entry(self):
        with self.assertRaises(ValueError):
            smm_store.add_item(self.smm_dir, "intent", "Bad", type="concern")

    def test_rejects_invalid_pillar(self):
        with self.assertRaises(ValueError):
            smm_store.add_item(self.smm_dir, "nonexistent", "content")

    def test_preserves_existing_entries(self):
        data = _minimal_smm(wisdom=[_VALID_ENTRY])
        smm_store.save_smm(self.smm_dir, data)
        smm_store.add_item(self.smm_dir, "wisdom", "New item")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 2)
        self.assertEqual(smm["wisdom"][0]["content"], "TDD always")
        self.assertEqual(smm["wisdom"][1]["content"], "New item")

    def test_with_optional_fields(self):
        uid = smm_store.add_item(
            self.smm_dir,
            "constraints",
            "Use REST",
            type="decision",
            topic="api-style",
        )
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["constraints"][0]
        self.assertEqual(entry["id"], uid)
        self.assertEqual(entry["type"], "decision")
        self.assertEqual(entry["topic"], "api-style")

    def test_with_severity(self):
        smm_store.add_item(
            self.smm_dir,
            "risks",
            "Auth fragile",
            type="concern",
            severity="problem",
        )
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["risks"][0]
        self.assertEqual(entry["severity"], "problem")

    def test_with_source_event_id(self):
        event_id = "aaabbbcccddd"
        smm_store.add_item(
            self.smm_dir,
            "wisdom",
            "Lesson learned",
            source="event",
            source_event_id=event_id,
        )
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["wisdom"][0]
        self.assertEqual(entry["source"], "event")
        self.assertEqual(entry["source_event_id"], event_id)

    def test_unique_ids_across_calls(self):
        uid1 = smm_store.add_item(self.smm_dir, "wisdom", "First")
        uid2 = smm_store.add_item(self.smm_dir, "wisdom", "Second")
        self.assertNotEqual(uid1, uid2)

    def test_rejects_over_budget_content(self):
        with self.assertRaises(ValueError) as ctx:
            smm_store.add_item(self.smm_dir, "wisdom", "x" * 151)
        self.assertIn("151", str(ctx.exception))
        self.assertIn("150", str(ctx.exception))

    def test_accepts_at_budget_content(self):
        uid = smm_store.add_item(self.smm_dir, "wisdom", "x" * 150)
        self.assertRegex(uid, r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------


class TestUpdateItem(_StoreTestCase):
    def setUp(self):
        super().setUp()
        self.uid = smm_store.add_item(
            self.smm_dir,
            "constraints",
            "Use REST",
            type="decision",
            topic="api-style",
        )

    def test_changes_content(self):
        smm_store.update_item(self.smm_dir, self.uid, content="Use GraphQL")
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["constraints"][0]
        self.assertEqual(entry["content"], "Use GraphQL")
        self.assertEqual(entry["id"], self.uid)

    def test_preserves_id_source_ts(self):
        smm_before = smm_store.load_smm(self.smm_dir)
        original = smm_before["constraints"][0]
        smm_store.update_item(self.smm_dir, self.uid, content="Updated")
        smm_after = smm_store.load_smm(self.smm_dir)
        updated = smm_after["constraints"][0]
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["source"], original["source"])
        self.assertEqual(updated["ts"], original["ts"])

    def test_patches_type(self):
        smm_store.update_item(self.smm_dir, self.uid, type="convention")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(smm["constraints"][0]["type"], "convention")

    def test_patches_optional_fields(self):
        smm_store.update_item(self.smm_dir, self.uid, topic="new-topic")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(smm["constraints"][0]["topic"], "new-topic")

    def test_raises_for_unknown_id(self):
        with self.assertRaises(ValueError):
            smm_store.update_item(
                self.smm_dir,
                "000000000000",
                content="nope",
            )

    def test_validates_after_patch(self):
        with self.assertRaises(ValueError):
            smm_store.update_item(self.smm_dir, self.uid, type="concern")

    def test_rejects_over_budget_content_update(self):
        with self.assertRaises(ValueError) as ctx:
            smm_store.update_item(self.smm_dir, self.uid, content="x" * 151)
        self.assertIn("151", str(ctx.exception))

    def test_finds_across_pillars(self):
        uid_risk = smm_store.add_item(
            self.smm_dir,
            "risks",
            "Fragile auth",
            type="concern",
            severity="problem",
        )
        smm_store.update_item(self.smm_dir, uid_risk, content="Very fragile auth")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(smm["risks"][0]["content"], "Very fragile auth")


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------


class TestRemoveItem(_StoreTestCase):
    def test_removes_entry(self):
        uid = smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        smm_store.remove_item(self.smm_dir, uid)
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 0)

    def test_raises_for_unknown_id(self):
        with self.assertRaises(ValueError):
            smm_store.remove_item(self.smm_dir, "000000000000")

    def test_leaves_other_entries(self):
        uid1 = smm_store.add_item(self.smm_dir, "wisdom", "First")
        smm_store.add_item(self.smm_dir, "wisdom", "Second")
        smm_store.remove_item(self.smm_dir, uid1)
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)
        self.assertEqual(smm["wisdom"][0]["content"], "Second")

    def test_finds_across_pillars(self):
        uid = smm_store.add_item(
            self.smm_dir,
            "risks",
            "Auth fragile",
            type="concern",
            severity="problem",
        )
        smm_store.add_item(self.smm_dir, "wisdom", "TDD always")
        smm_store.remove_item(self.smm_dir, uid)
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["risks"]), 0)
        self.assertEqual(len(smm["wisdom"]), 1)


# ---------------------------------------------------------------------------
# promote_event
# ---------------------------------------------------------------------------


class TestPromoteEvent(_SMMTestCase):
    def test_creates_entry_from_concern(self):
        event = make_event(
            EVENT_TYPE_CONCERN, content="Auth is fragile", severity="problem"
        )
        self._write_events([event])
        uid = smm_store.promote_event(self.smm_dir, event["id"])
        smm = smm_store.load_smm(self.smm_dir)
        entry = smm["risks"][0]
        self.assertEqual(entry["id"], uid)
        self.assertEqual(entry["content"], "Auth is fragile")
        self.assertEqual(entry["source"], "event")
        self.assertEqual(entry["source_event_id"], event["id"])
        self.assertEqual(entry["type"], "concern")
        self.assertEqual(entry["severity"], "problem")

    def test_maps_decision_to_constraints(self):
        event = make_event(EVENT_TYPE_DECISION, content="Use REST", topic="api-style")
        self._write_events([event])
        smm_store.promote_event(self.smm_dir, event["id"])
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["constraints"]), 1)
        entry = smm["constraints"][0]
        self.assertEqual(entry["type"], "decision")
        self.assertEqual(entry["topic"], "api-style")

    def test_maps_goal_to_intent(self):
        event = make_event(EVENT_TYPE_GOAL, content="Ship v1")
        self._write_events([event])
        smm_store.promote_event(self.smm_dir, event["id"])
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["intent"]), 1)
        self.assertEqual(smm["intent"][0]["type"], "goal")

    def test_maps_discovery_to_wisdom(self):
        event = make_event(EVENT_TYPE_DISCOVERY, content="Caching helps")
        self._write_events([event])
        smm_store.promote_event(self.smm_dir, event["id"])
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)

    def test_resolves_full_id(self):
        event = make_event(EVENT_TYPE_GOAL, content="Ship v1")
        self._write_events([event])
        uid = smm_store.promote_event(self.smm_dir, event["id"])
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["intent"]), 1)
        self.assertEqual(smm["intent"][0]["source_event_id"], event["id"])
        self.assertIsNotNone(uid)

    def test_raises_for_unknown_event(self):
        self._write_events([])
        with self.assertRaises(ValueError) as ctx:
            smm_store.promote_event(
                self.smm_dir,
                "000000000000",
            )
        self.assertIn("not found", str(ctx.exception).lower())

    def test_raises_for_ambiguous_prefix(self):
        e1 = make_event(
            EVENT_TYPE_GOAL,
            id="aabbccdd1111",
            content="First",
        )
        e2 = make_event(
            EVENT_TYPE_GOAL,
            id="aabbccdd2222",
            content="Second",
        )
        self._write_events([e1, e2])
        with self.assertRaises(ValueError) as ctx:
            smm_store.promote_event(self.smm_dir, "aabbccdd")
        self.assertIn("ambiguous", str(ctx.exception).lower())

    def test_returns_generated_id(self):
        event = make_event(EVENT_TYPE_GOAL, content="Ship v1")
        self._write_events([event])
        uid = smm_store.promote_event(self.smm_dir, event["id"])
        self.assertRegex(uid, r"^[0-9a-f]{12}$")
        self.assertNotEqual(uid, event["id"])

    def test_explicit_pillar_override(self):
        event = make_event(
            EVENT_TYPE_CONCERN, content="Might be wisdom", severity="problem"
        )
        self._write_events([event])
        smm_store.promote_event(self.smm_dir, event["id"], pillar="wisdom")
        smm = smm_store.load_smm(self.smm_dir)
        self.assertEqual(len(smm["wisdom"]), 1)
        self.assertEqual(len(smm["risks"]), 0)

    def test_raises_for_unmappable_type(self):
        event = make_event(EVENT_TYPE_STATUS, content="Working on it")
        self._write_events([event])
        with self.assertRaises(ValueError) as ctx:
            smm_store.promote_event(self.smm_dir, event["id"])
        self.assertIn("cannot", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
