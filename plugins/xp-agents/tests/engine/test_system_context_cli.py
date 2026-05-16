#!/usr/bin/env python3
"""Tests for system_context_cli.py: CLI wrapper for system context operations."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import read_events, seed_doc, valid_doc, write_doc
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
        principles_pos = output.find("Principles")
        custom_pos = output.find("Custom Section")
        self.assertTrue(
            product_pos
            < arch_pos
            < stack_pos
            < modules_pos
            < conv_pos
            < principles_pos
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
    `--topics-only` flag (subset of `--sections`) collapses `principles`
    to topic-bullets and `project_specific` to name-bullets, leaving the
    rest full.
    """

    def _write_doc_with_principles(self) -> None:
        doc = valid_doc()
        doc["principles"] = [
            {"topic": "hooks-first", "decision": "All agents are hooks"},
            {"topic": "four-file", "decision": "events + sc + plan + sprint"},
        ]
        doc["project_specific"] = [
            {"name": "lifecycle", "content": "story states ..."},
            {"name": "tiers", "content": "review tiers ..."},
        ]
        write_doc(self.smm_dir, doc)

    def test_sections_filter_keeps_only_named(self) -> None:
        self._write_doc_with_principles()
        result = run_cli(
            _CLI, ["render", "--sections", "stack,conventions"], self.smm_dir
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Stack", result.stdout)
        self.assertIn("## Conventions", result.stdout)
        self.assertNotIn("## Product", result.stdout)
        self.assertNotIn("## Architecture Overview", result.stdout)
        self.assertNotIn("## Modules", result.stdout)
        self.assertNotIn("## Principles", result.stdout)

    def test_topics_only_collapses_principles_to_topic_bullets(self) -> None:
        self._write_doc_with_principles()
        result = run_cli(
            _CLI,
            [
                "render",
                "--sections",
                "principles",
                "--topics-only",
                "principles",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("- hooks-first", result.stdout)
        self.assertIn("- four-file", result.stdout)
        self.assertNotIn("All agents are hooks", result.stdout)
        self.assertNotIn("events + sc + plan + sprint", result.stdout)

    def test_topics_only_collapses_project_specific_to_name_bullets(self) -> None:
        self._write_doc_with_principles()
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
        self._write_doc_with_principles()
        result = run_cli(
            _CLI,
            [
                "render",
                "--sections",
                "stack,principles",
                "--topics-only",
                "principles",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Stack", result.stdout)
        self.assertIn("Python", result.stdout)
        self.assertIn("- hooks-first", result.stdout)
        self.assertNotIn("All agents are hooks", result.stdout)

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
        result = run_cli(_CLI, ["render", "--topics-only", "principles"], self.smm_dir)
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


# ── add-principle ────────────────────────────────────────────────


class TestAddPrincipleCommand(_SMMTestCase):
    def test_add_principle(self) -> None:
        write_doc(self.smm_dir)
        new_principle = {"topic": "database", "decision": "Use SQLite"}
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data=json.dumps(new_principle),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 2)
        self.assertEqual(data["principles"][1]["topic"], "database")

    def test_add_principle_invalid_json(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid JSON", result.stderr)

    def test_add_principle_missing_file(self) -> None:
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data=json.dumps({"topic": "x", "decision": "y"}),
        )
        self.assertEqual(result.returncode, 1)


# ── count caps: soft warn / hard refuse on add-* ────────────────


class TestAddCommandCountCaps(_SMMTestCase):
    """Soft cap: stderr "approaching cap" + exit 0. Hard cap: stderr
    "hard cap reached" + retire-<kind> + non-zero exit; file unchanged."""

    # ── modules: soft=10, hard=15, add-module ──────────────────

    def test_add_modules_below_soft_silent(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 8))
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "purpose": "x", "path": "p"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("approaching", result.stderr)

    def test_add_modules_at_soft_warns_but_writes(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 10))
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "purpose": "x", "path": "p"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approaching cap", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["modules"]), 11)

    def test_add_modules_at_hard_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 15))
        result = run_cli(
            _CLI,
            ["add-module"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "purpose": "x", "path": "p"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard cap reached", result.stderr)
        self.assertIn("retire-module", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["modules"]), 15)

    # ── conventions: soft=20, hard=30, add-convention ──────────

    def test_add_conventions_below_soft_silent(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 18))
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data=json.dumps("new-convention"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("approaching", result.stderr)

    def test_add_conventions_at_soft_warns_but_writes(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 20))
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data=json.dumps("new-convention"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approaching cap", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 21)

    def test_add_conventions_at_hard_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 30))
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data=json.dumps("new-convention"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard cap reached", result.stderr)
        self.assertIn("retire-convention", result.stderr)

    # ── principles: soft=15, hard=20, add-principle ────────────

    def test_add_principles_below_soft_silent(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 13))
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data=json.dumps({"topic": "new", "decision": "d"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("approaching", result.stderr)

    def test_add_principles_at_soft_warns_but_writes(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 15))
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data=json.dumps({"topic": "new", "decision": "d"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approaching cap", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 16)

    def test_add_principles_at_hard_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 20))
        result = run_cli(
            _CLI,
            ["add-principle"],
            self.smm_dir,
            stdin_data=json.dumps({"topic": "new", "decision": "d"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard cap reached", result.stderr)
        self.assertIn("retire-principle", result.stderr)

    # ── project_specific: soft=10, hard=15 ─────────────────────
    # No add-project-specific CLI yet; entries are added via edit-field.
    # Constants pinned in test_system_context_schema.TestCountCaps.

    # ── acceptance_surfaces: soft=5, hard=8, add-acceptance-surface ─

    def test_add_acceptance_surfaces_below_soft_silent(self) -> None:
        write_doc(self.smm_dir, seed_doc("acceptance_surfaces", 3))
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(
                {"name": "new", "signals": ["x"], "status": "covered"}
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("approaching", result.stderr)

    def test_add_acceptance_surfaces_at_soft_warns_but_writes(self) -> None:
        write_doc(self.smm_dir, seed_doc("acceptance_surfaces", 5))
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(
                {"name": "new", "signals": ["x"], "status": "covered"}
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approaching cap", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 6)

    def test_add_acceptance_surfaces_at_hard_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("acceptance_surfaces", 8))
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(
                {"name": "new", "signals": ["x"], "status": "covered"}
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard cap reached", result.stderr)
        self.assertIn("retire-acceptance-surface", result.stderr)


# ── retire-* subcommands ────────────────────────────────────────


class TestRetireCommands(_SMMTestCase):
    """Retire-* CLIs remove an entry from a capped list and emit a status
    event so curation is traceable. Hard delete only — provenance survives
    in the original decision event."""

    # ── retire-principle (by topic) ────────────────────────────

    def test_retire_principle_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(_CLI, ["retire-principle", "t1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 2)
        self.assertNotIn("t1", [p["topic"] for p in data["principles"]])

    def test_retire_principle_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        result = run_cli(_CLI, ["retire-principle", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["principles"]), 3)

    def test_retire_principle_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("principles", 3))
        run_cli(_CLI, ["retire-principle", "t1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_principle"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "t1")
        self.assertEqual(retire_events[0]["metadata"]["kind"], "principle")

    # ── retire-module (by name) ────────────────────────────────

    def test_retire_module_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(_CLI, ["retire-module", "m1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["modules"]), 2)
        self.assertNotIn("m1", [m["name"] for m in data["modules"]])

    def test_retire_module_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        result = run_cli(_CLI, ["retire-module", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_module_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("modules", 3))
        run_cli(_CLI, ["retire-module", "m1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e for e in events if e.get("metadata", {}).get("action") == "retire_module"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "m1")

    # ── retire-project-specific (by name) ──────────────────────

    def test_retire_project_specific_success(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        result = run_cli(_CLI, ["retire-project-specific", "ps1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["project_specific"]), 2)
        self.assertNotIn("ps1", [e["name"] for e in data["project_specific"]])

    def test_retire_project_specific_not_found(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        result = run_cli(_CLI, ["retire-project-specific", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_project_specific_emits_status_event(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 3))
        run_cli(_CLI, ["retire-project-specific", "ps1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_project_specific"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "ps1")

    # ── retire-acceptance-surface (by name) ────────────────────

    def test_retire_acceptance_surface_success(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-acceptance-surface", "s1"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 2)
        self.assertNotIn("s1", [s["name"] for s in data["acceptance_surfaces"]])

    def test_retire_acceptance_surface_not_found(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-acceptance-surface", "missing"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_retire_acceptance_surface_emits_status_event(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = seed_doc("acceptance_surfaces", 3)[
            "acceptance_surfaces"
        ]
        write_doc(self.smm_dir, doc)
        run_cli(_CLI, ["retire-acceptance-surface", "s1"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_acceptance_surface"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(retire_events[0]["metadata"]["identifier"], "s1")

    # ── retire-convention (by index or substring) ──────────────

    def test_retire_convention_by_integer_index(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 5))
        result = run_cli(_CLI, ["retire-convention", "2"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 4)
        self.assertNotIn("c2", data["conventions"])

    def test_retire_convention_integer_index_out_of_range(self) -> None:
        write_doc(self.smm_dir, seed_doc("conventions", 3))
        result = run_cli(_CLI, ["retire-convention", "99"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("out of range", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 3)

    def test_retire_convention_by_substring(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
            "Atomic writes via tempfile + rename",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-convention", "pathlib"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 2)
        self.assertNotIn("Prefer pathlib over os.path", data["conventions"])

    def test_retire_convention_ambiguous_substring_refuses(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Use pathlib",
            "Use atomic writes",
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["retire-convention", "Use"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr.lower())
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["conventions"]), 3)

    def test_retire_convention_emits_status_event_with_resolved_text(self) -> None:
        doc = valid_doc()
        doc["conventions"] = [
            "Use type hints",
            "Prefer pathlib over os.path",
            "Atomic writes via tempfile + rename",
        ]
        write_doc(self.smm_dir, doc)
        run_cli(_CLI, ["retire-convention", "pathlib"], self.smm_dir)
        events = read_events(self.smm_dir)
        retire_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "retire_convention"
        ]
        self.assertEqual(len(retire_events), 1)
        self.assertEqual(
            retire_events[0]["metadata"]["identifier"],
            "Prefer pathlib over os.path",
        )


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
