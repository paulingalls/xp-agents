#!/usr/bin/env python3
"""Tests for system_context_cli.py: CLI wrapper for system context operations."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc, write_doc
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


# ── exists ──────────────────────────────────────────────────────


class TestExistsCommand(_SMMTestCase):
    def test_exists_when_present(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists_when_missing(self) -> None:
        result = run_cli(_CLI, ["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


# ── validate ────────────────────────────────────────────────────


class TestValidateCommand(_SMMTestCase):
    def test_validatevalid_doc(self) -> None:
        write_doc(self.smm_dir)
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
    def test_createvalid_doc(self) -> None:
        doc = valid_doc()
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

    def test_create_preserves_branching_strategy_when_omitted(self) -> None:
        existing = valid_doc()
        existing["branching_strategy"] = {
            "stage": 2,
            "user_namespace": "paul",
            "protected_branches": ["main"],
        }
        write_doc(self.smm_dir, existing)

        incoming = valid_doc()
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertIn("branching_strategy", data)
        self.assertEqual(data["branching_strategy"]["stage"], 2)
        self.assertEqual(data["branching_strategy"]["user_namespace"], "paul")

    def test_create_preserves_acceptance_surfaces_when_omitted(self) -> None:
        existing = valid_doc()
        existing["acceptance_surfaces"] = [
            {"name": "tests", "signals": ["pytest"], "status": "covered"}
        ]
        write_doc(self.smm_dir, existing)

        incoming = valid_doc()
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertIn("acceptance_surfaces", data)
        self.assertEqual(data["acceptance_surfaces"][0]["name"], "tests")

    def test_create_explicit_null_wipes_branching_strategy(self) -> None:
        existing = valid_doc()
        existing["branching_strategy"] = {"stage": 2}
        write_doc(self.smm_dir, existing)

        incoming = valid_doc()
        incoming["branching_strategy"] = None
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("branching_strategy", data)

    def test_create_explicit_null_wipes_acceptance_surfaces(self) -> None:
        existing = valid_doc()
        existing["acceptance_surfaces"] = [
            {"name": "tests", "signals": ["pytest"], "status": "covered"}
        ]
        write_doc(self.smm_dir, existing)

        incoming = valid_doc()
        incoming["acceptance_surfaces"] = None
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("acceptance_surfaces", data)

    def test_create_fresh_without_optional_fields(self) -> None:
        incoming = valid_doc()
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("branching_strategy", data)
        self.assertNotIn("acceptance_surfaces", data)


# ── render ──────────────────────────────────────────────────────


class TestRenderCommand(_SMMTestCase):
    def test_render_canonical_order(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [
            {"name": "Custom Section", "content": "Custom content"}
        ]
        write_doc(self.smm_dir, doc)
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
        doc = valid_doc()
        doc["project_specific"] = [{"name": "Notes", "content": "Some prose notes."}]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("Some prose notes.", result.stdout)

    def test_render_project_specific_list_of_strings(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "Items", "content": ["item1", "item2"]}]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("- item1", result.stdout)
        self.assertIn("- item2", result.stdout)

    def test_render_project_specific_list_of_objects(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [
            {
                "name": "Hooks",
                "content": [
                    {"event": "PreToolUse", "action": "validate"},
                    {"event": "PostToolUse", "action": "record"},
                ],
            }
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("event", result.stdout)
        self.assertIn("PreToolUse", result.stdout)
        self.assertIn("PostToolUse", result.stdout)

    def test_render_project_specific_object(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [
            {"name": "Config", "content": {"key": "value", "debug": "false"}}
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("key", result.stdout)
        self.assertIn("value", result.stdout)


# ── render --sections / --topics-only ──────────────────────────


class TestRenderSubsetFlags(_SMMTestCase):
    """Reviewer-scoped render subsets.

    Plan + close reviewers don't need the full ~7K-token document. The
    `--sections` flag filters which top-level keys are rendered; the
    `--topics-only` flag (subset of `--sections`) collapses `key_decisions`
    to topic-bullets and `project_specific` to name-bullets, leaving the
    rest full.
    """

    def _write_doc_with_decisions(self) -> None:
        doc = valid_doc()
        doc["key_decisions"] = [
            {"topic": "hooks-first", "decision": "All agents are hooks"},
            {"topic": "four-file", "decision": "events + sc + plan + sprint"},
        ]
        doc["project_specific"] = [
            {"name": "lifecycle", "content": "story states ..."},
            {"name": "tiers", "content": "review tiers ..."},
        ]
        write_doc(self.smm_dir, doc)

    def test_sections_filter_keeps_only_named(self) -> None:
        self._write_doc_with_decisions()
        result = run_cli(
            _CLI, ["render", "--sections", "stack,conventions"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Stack", result.stdout)
        self.assertIn("## Conventions", result.stdout)
        self.assertNotIn("## Product", result.stdout)
        self.assertNotIn("## Architecture Overview", result.stdout)
        self.assertNotIn("## Modules", result.stdout)
        self.assertNotIn("## Key Decisions", result.stdout)

    def test_topics_only_collapses_key_decisions_to_topic_bullets(self) -> None:
        self._write_doc_with_decisions()
        result = run_cli(
            _CLI,
            [
                "render",
                "--sections",
                "key_decisions",
                "--topics-only",
                "key_decisions",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- hooks-first", result.stdout)
        self.assertIn("- four-file", result.stdout)
        self.assertNotIn("All agents are hooks", result.stdout)
        self.assertNotIn("events + sc + plan + sprint", result.stdout)

    def test_topics_only_collapses_project_specific_to_name_bullets(self) -> None:
        self._write_doc_with_decisions()
        result = run_cli(
            _CLI,
            [
                "render",
                "--sections",
                "project_specific",
                "--topics-only",
                "project_specific",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- lifecycle", result.stdout)
        self.assertIn("- tiers", result.stdout)
        self.assertNotIn("story states", result.stdout)
        self.assertNotIn("review tiers", result.stdout)

    def test_mixed_topics_only_and_full_section(self) -> None:
        self._write_doc_with_decisions()
        result = run_cli(
            _CLI,
            [
                "render",
                "--sections",
                "stack,key_decisions",
                "--topics-only",
                "key_decisions",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Stack", result.stdout)
        self.assertIn("Python", result.stdout)  # stack content present
        self.assertIn("- hooks-first", result.stdout)  # kd as TOC
        self.assertNotIn("All agents are hooks", result.stdout)  # kd body absent

    def test_unknown_section_errors_with_valid_names(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI, ["render", "--sections", "stack,bogus_name"], self.smm_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bogus_name", result.stderr)
        self.assertIn("stack", result.stderr)  # valid names listed

    def test_topics_only_on_non_identifier_section_errors(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["render", "--sections", "stack", "--topics-only", "stack"],
            self.smm_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stack", result.stderr)

    def test_topics_only_without_sections_errors(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI, ["render", "--topics-only", "key_decisions"], self.smm_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--sections", result.stderr)


# ── section ─────────────────────────────────────────────────────


class TestSectionCommand(_SMMTestCase):
    def test_section_generic_field(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["section", "product"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("A test product.", result.stdout)

    def test_section_project_specific(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "Custom", "content": "Custom data"}]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["section", "Custom"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Custom data", result.stdout)

    def test_section_unknown_name(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["section", "nonexistent"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_section_missing_file(self) -> None:
        result = run_cli(_CLI, ["section", "product"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


# ── edit-field ──────────────────────────────────────────────────


class TestEditFieldCommand(_SMMTestCase):
    def test_edit_field_string(self) -> None:
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-field", "nonexistent"],
            self.smm_dir,
            stdin_data=json.dumps("value"),
        )
        self.assertEqual(result.returncode, 1)

    def test_edit_field_project_specific(self) -> None:
        doc = valid_doc()
        doc["project_specific"] = [{"name": "Custom", "content": "Old content"}]
        write_doc(self.smm_dir, doc)
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
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
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
        write_doc(self.smm_dir)
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


# ── e2e ────────────────────────────────────────────────────────


class TestE2E(_SMMTestCase):
    def test_create_edit_render_roundtrip(self) -> None:
        doc = valid_doc()
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
