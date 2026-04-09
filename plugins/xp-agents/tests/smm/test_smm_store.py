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


def _minimal_smm(**overrides):
    """Build a minimal valid SMM dict."""
    base = smm_schema.empty_smm()
    base.update(overrides)
    return base


_VALID_ENTRY = {
    "id": "11111111-2222-4333-8444-555555555555",
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
        data = _minimal_smm(constraints=[{**_VALID_ENTRY, "type": "convention"}])
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
            "type": "goal",
            "source_event_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        }
        data = _minimal_smm(intent=[entry])
        smm_store.save_smm(self.smm_dir, data)
        result = smm_store.load_smm(self.smm_dir)
        self.assertEqual(
            result["intent"][0]["source_event_id"],
            entry["source_event_id"],
        )
        self.assertEqual(result["intent"][0]["type"], "goal")


if __name__ == "__main__":
    unittest.main()
