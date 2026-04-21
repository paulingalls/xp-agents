#!/usr/bin/env python3
"""Tests for system_context_cli.py: CLI wrapper for system context operations."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


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


def _write_doc(smm_dir: Path, doc: dict | None = None) -> None:
    """Write a valid system context doc to the SMM directory."""
    (smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(json.dumps(doc or _valid_doc()))


# ── exists ──────────────────────────────────────────────────────


class TestExistsCommand(_SMMTestCase):
    def test_exists_when_present(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists_when_missing(self) -> None:
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


# ── validate ────────────────────────────────────────────────────


class TestValidateCommand(_SMMTestCase):
    def test_validate_valid_doc(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(_CLI, ["validate"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_validate_invalid_doc(self) -> None:
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps({"bad": "schema"})
        )
        result = run_cli(_CLI, ["validate"], self.smm_dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing required field", result.stderr)

    def test_validate_missing_file(self) -> None:
        result = run_cli(_CLI, ["validate"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


# ── create ──────────────────────────────────────────────────────


class TestCreateCommand(_SMMTestCase):
    def test_create_valid_doc(self) -> None:
        doc = _valid_doc()
        result = run_cli(_CLI, ["create"], self.smm_dir, stdin_data=json.dumps(doc))
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.smm_dir / SYSTEM_CONTEXT_FILENAME).exists())

    def test_create_invalid_json(self) -> None:
        result = run_cli(_CLI, ["create"], self.smm_dir, stdin_data="not json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSON", result.stderr)

    def test_create_invalid_schema(self) -> None:
        result = run_cli(
            _CLI,
            ["create"],
            self.smm_dir,
            stdin_data=json.dumps({"bad": "data"}),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Validation error", result.stderr)


# ── render ──────────────────────────────────────────────────────


class TestRenderCommand(_SMMTestCase):
    def test_render_canonical_order(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [
            {"name": "Custom Section", "content": "Custom content"}
        ]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        output = result.stdout
        product_pos = output.find("Product")
        arch_pos = output.find("Architecture")
        stack_pos = output.find("Stack")
        modules_pos = output.find("Modules")
        conv_pos = output.find("Conventions")
        decisions_pos = output.find("Key Decisions")
        sources_pos = output.find("Sources")
        custom_pos = output.find("Custom Section")
        self.assertTrue(
            product_pos
            < arch_pos
            < stack_pos
            < modules_pos
            < conv_pos
            < decisions_pos
            < sources_pos
            < custom_pos,
            f"Sections not in canonical order: {output[:500]}",
        )

    def test_render_missing_file(self) -> None:
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_render_project_specific_string(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [{"name": "Notes", "content": "Some prose notes."}]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("Some prose notes.", result.stdout)

    def test_render_project_specific_list_of_strings(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [{"name": "Items", "content": ["item1", "item2"]}]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("- item1", result.stdout)
        self.assertIn("- item2", result.stdout)

    def test_render_project_specific_list_of_objects(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [
            {
                "name": "Hooks",
                "content": [
                    {"event": "PreToolUse", "action": "validate"},
                    {"event": "PostToolUse", "action": "record"},
                ],
            }
        ]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("event", result.stdout)
        self.assertIn("PreToolUse", result.stdout)
        self.assertIn("PostToolUse", result.stdout)

    def test_render_project_specific_object(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [
            {"name": "Config", "content": {"key": "value", "debug": "false"}}
        ]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("key", result.stdout)
        self.assertIn("value", result.stdout)


# ── section ─────────────────────────────────────────────────────


class TestSectionCommand(_SMMTestCase):
    def test_section_generic_field(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(_CLI, ["section", "product"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("A test product.", result.stdout)

    def test_section_project_specific(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [{"name": "Custom", "content": "Custom data"}]
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["section", "Custom"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Custom data", result.stdout)

    def test_section_unknown_name(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(_CLI, ["section", "nonexistent"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_section_missing_file(self) -> None:
        result = run_cli(_CLI, ["section", "product"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


# ── edit-field ──────────────────────────────────────────────────


class TestEditFieldCommand(_SMMTestCase):
    def test_edit_field_string(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-field", "product"],
            self.smm_dir,
            stdin_data=json.dumps("Updated product"),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["product"], "Updated product")

    def test_edit_field_preserves_other_fields(self) -> None:
        _write_doc(self.smm_dir)
        run_cli(
            _CLI,
            ["edit-field", "product"],
            self.smm_dir,
            stdin_data=json.dumps("New product"),
        )
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["architecture_overview"], "Simple architecture.")

    def test_edit_field_missing_file(self) -> None:
        result = run_cli(
            _CLI,
            ["edit-field", "product"],
            self.smm_dir,
            stdin_data=json.dumps("value"),
        )
        self.assertEqual(result.returncode, 1)

    def test_edit_field_unknown_field(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-field", "nonexistent"],
            self.smm_dir,
            stdin_data=json.dumps("value"),
        )
        self.assertEqual(result.returncode, 1)

    def test_edit_field_project_specific(self) -> None:
        doc = _valid_doc()
        doc["project_specific"] = [{"name": "Custom", "content": "Old content"}]
        _write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-field", "Custom"],
            self.smm_dir,
            stdin_data=json.dumps("New content"),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["project_specific"][0]["content"], "New content")

    def test_edit_field_invalid_json(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-field", "product"],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSON", result.stderr)


# ── add-module ──────────────────────────────────────────────────


class TestAddModuleCommand(_SMMTestCase):
    def test_add_module(self) -> None:
        _write_doc(self.smm_dir)
        new_module = {"name": "api", "purpose": "API layer", "path": "src/api"}
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data=json.dumps(new_module),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["modules"]), 2)
        self.assertEqual(data["modules"][1]["name"], "api")

    def test_add_module_invalid_json(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSON", result.stderr)

    def test_add_module_missing_file(self) -> None:
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "x", "purpose": "y", "path": "z"}),
        )
        self.assertEqual(result.returncode, 1)


# ── add-decision ────────────────────────────────────────────────


class TestAddDecisionCommand(_SMMTestCase):
    def test_add_decision(self) -> None:
        _write_doc(self.smm_dir)
        new_decision = {"topic": "database", "decision": "Use SQLite"}
        result = run_cli(
            _CLI,
            ["add-decision"],
            self.smm_dir,
            stdin_data=json.dumps(new_decision),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["key_decisions"]), 2)
        self.assertEqual(data["key_decisions"][1]["topic"], "database")

    def test_add_decision_invalid_json(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-decision"],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSON", result.stderr)

    def test_add_decision_missing_file(self) -> None:
        result = run_cli(
            _CLI,
            ["add-decision"],
            self.smm_dir,
            stdin_data=json.dumps({"topic": "x", "decision": "y"}),
        )
        self.assertEqual(result.returncode, 1)


# ── E2E ─────────────────────────────────────────────────────────


class TestE2E(_SMMTestCase):
    def test_create_edit_render_roundtrip(self) -> None:
        doc = _valid_doc()
        run_cli(_CLI, ["create"], self.smm_dir, stdin_data=json.dumps(doc))

        run_cli(
            _CLI,
            ["edit-field", "product"],
            self.smm_dir,
            stdin_data=json.dumps("Updated product description"),
        )

        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Updated product description", result.stdout)
        self.assertNotIn("A test product.", result.stdout)


if __name__ == "__main__":
    unittest.main()
