#!/usr/bin/env python3
"""Tests for system_context_store.py — load/save/exists for system_context.json."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import marker_names
from conftest import _SMMTestCase
from system_context_schema import (
    FIELD_MAXLENGTH,
    SYSTEM_CONTEXT_FILENAME,
)
from system_context_store import (
    load_system_context,
    save_system_context,
    system_context_exists,
)


def _valid_doc() -> dict:
    """Return a minimal valid system context document."""
    return {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }


class TestSystemContextExists(_SMMTestCase):
    def test_exists_true_for_file(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps(_valid_doc()))
        self.assertTrue(system_context_exists(self.smm_dir))

    def test_exists_false_for_missing(self) -> None:
        self.assertFalse(system_context_exists(self.smm_dir))

    def test_exists_false_for_symlink(self) -> None:
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_valid_doc()))
        link = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        link.symlink_to(real)
        self.assertFalse(system_context_exists(self.smm_dir))


class TestLoadSystemContext(_SMMTestCase):
    def test_load_missing_returns_none(self) -> None:
        result = load_system_context(self.smm_dir)
        self.assertIsNone(result)

    def test_load_valid_document(self) -> None:
        doc = _valid_doc()
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps(doc))
        result = load_system_context(self.smm_dir)
        self.assertEqual(result, doc)

    def test_load_corrupt_raises(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text("not json {{{")
        with self.assertRaises(ValueError) as ctx:
            load_system_context(self.smm_dir)
        self.assertIn("Corrupt", str(ctx.exception))

    def test_load_invalid_schema_raises(self) -> None:
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        path.write_text(json.dumps({"bad": "schema"}))
        with self.assertRaises(ValueError) as ctx:
            load_system_context(self.smm_dir)
        self.assertIn("Schema-invalid", str(ctx.exception))

    def test_load_symlink_raises(self) -> None:
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(_valid_doc()))
        link = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            load_system_context(self.smm_dir)


class TestSaveSystemContext(_SMMTestCase):
    def test_save_and_load_roundtrip(self) -> None:
        doc = _valid_doc()
        save_system_context(self.smm_dir, doc)
        result = load_system_context(self.smm_dir)
        self.assertEqual(result, doc)

    def test_save_validates(self) -> None:
        with self.assertRaises(ValueError):
            save_system_context(self.smm_dir, {"bad": "data"})
        path = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        self.assertFalse(path.exists())

    def test_save_clears_marker(self) -> None:
        marker = self.smm_dir / marker_names.NEEDS_SYSTEM_CONTEXT
        marker.write_text("")
        save_system_context(self.smm_dir, _valid_doc())
        self.assertFalse(marker.exists())

    def test_save_symlink_raises(self) -> None:
        real = self.smm_dir / "real.json"
        real.write_text("{}")
        link = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        link.symlink_to(real)
        with self.assertRaises(OSError):
            save_system_context(self.smm_dir, _valid_doc())

    def test_save_enforce_budget_false(self) -> None:
        doc = _valid_doc()
        doc["product"] = "x" * (FIELD_MAXLENGTH["product"] + 100)
        save_system_context(self.smm_dir, doc, enforce_budget=False)
        result = load_system_context(self.smm_dir)
        self.assertEqual(result["product"], doc["product"])

    def test_save_rejects_over_budget_by_default(self) -> None:
        doc = _valid_doc()
        doc["product"] = "x" * (FIELD_MAXLENGTH["product"] + 1)
        with self.assertRaises(ValueError):
            save_system_context(self.smm_dir, doc)


if __name__ == "__main__":
    unittest.main()
