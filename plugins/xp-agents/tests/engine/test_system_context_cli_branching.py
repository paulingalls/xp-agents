#!/usr/bin/env python3
"""Tests for system_context_cli.py edit-branching, edit-acceptance-surfaces,
and render branching-strategy subcommands.

Distinct from test_system_context_branching.py which covers schema-level
validation, not CLI behavior.
"""

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


# ── edit-stack-field ───────────────────────────────────────────


class TestEditStackFieldCommand(_SMMTestCase):
    """edit-stack-field is the affordance for setting nested stack
    fields (test_command, runtime, etc.) without rewriting the entire
    stack object via edit-field. Top-level edit-field can't reach
    nested keys, so this subcommand exists.
    """

    def test_edit_stack_field_sets_test_command(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-stack-field", "test_command"],
            self.smm_dir,
            stdin_data='"pytest -n auto"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["stack"]["test_command"], "pytest -n auto")

    def test_edit_stack_field_preserves_other_stack_fields(self) -> None:
        # Setting test_command must not clobber languages, runtime,
        # package_manager, etc. that the user already configured.
        doc = valid_doc()
        doc["stack"]["runtime"] = "Python 3.11+"
        doc["stack"]["package_manager"] = "pipx"
        write_doc(self.smm_dir, doc=doc)
        result = run_cli(
            _CLI,
            ["edit-stack-field", "test_command"],
            self.smm_dir,
            stdin_data='"npm test"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["stack"]["test_command"], "npm test")
        self.assertEqual(data["stack"]["runtime"], "Python 3.11+")
        self.assertEqual(data["stack"]["package_manager"], "pipx")
        self.assertEqual(data["stack"]["languages"], doc["stack"]["languages"])

    def test_edit_stack_field_null_clears_field(self) -> None:
        doc = valid_doc()
        doc["stack"]["test_command"] = "pytest"
        write_doc(self.smm_dir, doc=doc)
        result = run_cli(
            _CLI,
            ["edit-stack-field", "test_command"],
            self.smm_dir,
            stdin_data="null",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("test_command", data["stack"])

    def test_edit_stack_field_validates_string_only(self) -> None:
        # The schema rejects non-string optional stack fields. The CLI
        # must surface that validation error rather than silently
        # writing an invalid doc.
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-stack-field", "test_command"],
            self.smm_dir,
            stdin_data='["pytest", "-n", "auto"]',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Validation error", result.stderr)

    def test_edit_stack_field_no_existing_context(self) -> None:
        result = run_cli(
            _CLI,
            ["edit-stack-field", "test_command"],
            self.smm_dir,
            stdin_data='"pytest"',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("No system context found", result.stderr)


# ── add-convention ─────────────────────────────────────────────


class TestAddConventionCommand(_SMMTestCase):
    """add-convention closes the asymmetry where add-module,
    add-decision, and add-acceptance-surface all exist for list
    fields but conventions had no append helper, forcing callers to
    rewrite the whole list via edit-field conventions.
    """

    def test_add_convention_appends_to_empty_list(self) -> None:
        # Default valid_doc() ships with a single seed convention; we
        # extend it. The point of the test is to assert the CLI appends
        # rather than replaces — pin via length check + tail content.
        write_doc(self.smm_dir)
        before = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())[
            "conventions"
        ]
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data='"Use match/case for tool routing"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())[
            "conventions"
        ]
        self.assertEqual(
            len(after),
            len(before) + 1,
            "add-convention must append, not replace",
        )
        self.assertEqual(after[-1], "Use match/case for tool routing")

    def test_add_convention_preserves_existing(self) -> None:
        # Critical contract: appending must not lose prior entries.
        # If a future refactor accidentally turns add-convention into
        # a setter, this test catches it.
        doc = valid_doc()
        doc["conventions"] = ["First", "Second"]
        write_doc(self.smm_dir, doc=doc)
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data='"Third"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["conventions"], ["First", "Second", "Third"])

    def test_add_convention_no_existing_context(self) -> None:
        result = run_cli(
            _CLI,
            ["add-convention"],
            self.smm_dir,
            stdin_data='"any"',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("No system context found", result.stderr)


# ── edit-branching ─────────────────────────────────────────────


class TestEditBranchingCommand(_SMMTestCase):
    def test_edit_branching_valid(self) -> None:
        write_doc(self.smm_dir)
        bs = {"stage": 1, "user_namespace": "paul"}
        result = run_cli(
            _CLI,
            ["edit-branching"],
            self.smm_dir,
            stdin_data=json.dumps(bs),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["branching_strategy"]["stage"], 1)
        self.assertEqual(data["branching_strategy"]["user_namespace"], "paul")

    def test_edit_branching_invalid_stage(self) -> None:
        write_doc(self.smm_dir)
        bs = {"stage": 5}
        result = run_cli(
            _CLI,
            ["edit-branching"],
            self.smm_dir,
            stdin_data=json.dumps(bs),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Validation error", result.stderr)

    def test_edit_branching_no_existing_context(self) -> None:
        bs = {"stage": 1}
        result = run_cli(
            _CLI,
            ["edit-branching"],
            self.smm_dir,
            stdin_data=json.dumps(bs),
        )
        self.assertEqual(result.returncode, 1)

    def test_edit_branching_replaces_existing(self) -> None:
        doc = valid_doc()
        doc["branching_strategy"] = {"stage": 0}
        write_doc(self.smm_dir, doc)
        bs = {"stage": 2, "protected_branches": ["main"]}
        result = run_cli(
            _CLI,
            ["edit-branching"],
            self.smm_dir,
            stdin_data=json.dumps(bs),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["branching_strategy"]["stage"], 2)

    def test_edit_branching_null_wipes_field(self) -> None:
        # Symmetry with _cmd_create: explicit null on an optional top-level
        # field (branching_strategy / acceptance_surfaces) wipes the field
        # rather than storing literal None (which would fail schema
        # validation). Both CLI entry points to optional fields agree on
        # null-as-wipe semantics.
        doc = valid_doc()
        doc["branching_strategy"] = {"stage": 2, "protected_branches": ["main"]}
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-branching"],
            self.smm_dir,
            stdin_data="null",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("branching_strategy", data)

    def test_edit_acceptance_surfaces_null_wipes_field(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [
            {"name": "cli", "signals": ["x"], "status": "covered"}
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surfaces"],
            self.smm_dir,
            stdin_data="null",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("acceptance_surfaces", data)


# ── render branching strategy ──────────────────────────────────


class TestRenderBranchingStrategy(_SMMTestCase):
    def test_render_includes_branching_strategy(self) -> None:
        doc = valid_doc()
        doc["branching_strategy"] = {
            "stage": 2,
            "user_namespace": "paul",
            "protected_branches": ["main"],
            "rationale": "Team project with CI",
        }
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Branching Strategy", result.stdout)
        self.assertIn("Stage 2", result.stdout)
        self.assertIn("paul", result.stdout)
        self.assertIn("main", result.stdout)

    def test_render_omits_when_absent(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Branching Strategy", result.stdout)

    def test_render_shows_integration_branch(self) -> None:
        doc = valid_doc()
        doc["branching_strategy"] = {
            "stage": 3,
            "integration_branch": "develop",
        }
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("develop", result.stdout)

    def test_section_command_returns_branching(self) -> None:
        doc = valid_doc()
        doc["branching_strategy"] = {"stage": 1}
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["section", "branching_strategy"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Stage 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
