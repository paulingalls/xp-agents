#!/usr/bin/env python3
"""Tests for system_context_cli.py: edit-field, add-*, count-cap, and e2e commands.

Split from test_system_context_cli.py (over the 500-line cap); exists/
validate/create and render/section commands live in the basic/render
siblings.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import seed_doc, valid_doc, write_doc
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


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

    # ── project_specific: soft=10, hard=15, add-project-specific ──

    def test_add_project_specific_below_soft_silent(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 8))
        result = run_cli(
            _CLI,
            ["add-project-specific"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "content": "x"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("approaching", result.stderr)

    def test_add_project_specific_at_soft_warns_but_writes(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 10))
        result = run_cli(
            _CLI,
            ["add-project-specific"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "content": "x"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("approaching cap", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["project_specific"]), 11)

    def test_add_project_specific_at_hard_refuses(self) -> None:
        write_doc(self.smm_dir, seed_doc("project_specific", 15))
        result = run_cli(
            _CLI,
            ["add-project-specific"],
            self.smm_dir,
            stdin_data=json.dumps({"name": "new", "content": "x"}),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hard cap reached", result.stderr)
        self.assertIn("retire-project-specific", result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["project_specific"]), 15)

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


# ── retire-* + edit-* subcommands ───────────────────────────────
# retire-* tests live in test_system_context_cli_retire.py;
# edit-* tests live in test_system_context_cli_edit.py.


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
