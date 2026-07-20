#!/usr/bin/env python3
"""Tests for system_context_cli.py: render and section commands.

Split from test_system_context_cli.py (over the 500-line cap); exists/
validate/create and edit/add/e2e commands live in the basic/additions
siblings.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc, write_doc
from conftest import _SMMTestCase, run_cli

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


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


if __name__ == "__main__":
    unittest.main()
