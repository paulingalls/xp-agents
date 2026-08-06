#!/usr/bin/env python3
"""Tests for acceptance_surfaces CLI commands in system_context_cli.py.

Separate file to keep test_system_context_cli.py under 500 lines.
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


def _surface(**overrides: object) -> dict:
    base: dict = {
        "name": "browser",
        "signals": ["Next.js in package.json"],
        "status": "covered",
    }
    base.update(overrides)
    return base


class TestRenderAcceptanceSurfaces(_SMMTestCase):
    def test_render_includes_acceptance_surfaces(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [
            _surface(harness="playwright"),
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Acceptance Surfaces", result.stdout)
        self.assertIn("browser", result.stdout)
        self.assertIn("covered", result.stdout)
        self.assertIn("playwright", result.stdout)

    def test_render_omits_when_absent(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Acceptance Surfaces", result.stdout)

    def test_render_shows_gap_status(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface(status="gap")]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("gap", result.stdout)


class TestEditAcceptanceSurfaces(_SMMTestCase):
    def test_edit_replaces_field(self) -> None:
        write_doc(self.smm_dir)
        surfaces = [_surface(), _surface(name="cli", status="gap")]
        result = run_cli(
            _CLI,
            ["edit-acceptance-surfaces"],
            self.smm_dir,
            stdin_data=json.dumps(surfaces),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 2)

    def test_edit_invalid_data_rejected(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surfaces"],
            self.smm_dir,
            stdin_data=json.dumps([{"bad": "entry"}]),
        )
        self.assertNotEqual(result.returncode, 0)


class TestAddAcceptanceSurface(_SMMTestCase):
    def test_add_appends_surface(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface()]
        write_doc(self.smm_dir, doc)
        new = _surface(name="cli", status="gap")
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(new),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 2)
        self.assertEqual(data["acceptance_surfaces"][1]["name"], "cli")

    def test_add_to_empty_creates_list(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(_surface()),
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(len(data["acceptance_surfaces"]), 1)


class TestSectionAcceptanceSurfaces(_SMMTestCase):
    def test_section_renders_acceptance_surfaces(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface(harness="playwright")]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["section", "acceptance_surfaces"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("browser", result.stdout)
        self.assertIn("playwright", result.stdout)


class TestUnknownSurfaceKeyRejectedAtAuthoring(_SMMTestCase):
    """A misspelt surface field must be loud where it is AUTHORED.

    `cmd` for `command` or `path` for `paths` would otherwise validate clean
    and select nothing forever — configured-looking and inert. The check lives
    at the CLI, deliberately NOT in `validate_system_context`: that validator
    also runs on the READ path (`load_system_context` raises), and
    `branching_stage._maybe_auto_promote` does a load -> mutate -> save
    round-trip on a hook path while explicitly not catching ValueError. A
    document-wide rule would turn one stray key in an existing project's file
    into a crashed hook on upgrade.
    """

    def test_add_rejects_an_unknown_key(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(_surface(cmd="pytest tests/cli")),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("cmd", result.stderr)

    def test_add_accepts_the_known_optional_fields(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["add-acceptance-surface"],
            self.smm_dir,
            stdin_data=json.dumps(
                _surface(command="pytest tests/cli", paths=["src/cli/**"])
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["acceptance_surfaces"][0]["command"], "pytest tests/cli")

    def test_replace_all_rejects_an_unknown_key(self) -> None:
        """The analyzer's path: edit-acceptance-surfaces replaces the WHOLE
        array, so it is an authoring boundary too."""
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surfaces"],
            self.smm_dir,
            stdin_data=json.dumps([_surface(path=["src/**"])]),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("path", result.stderr)

    def test_edit_one_rejects_an_unknown_key(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface()]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surface", "browser"],
            self.smm_dir,
            stdin_data=json.dumps({"cmd": "pytest"}),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("cmd", result.stderr)

    def test_edit_one_still_clears_a_stray_key_with_null(self) -> None:
        """A `null` patch value REMOVES a key, so the unknown-key check must
        not refuse it — a document that already carries a stray key would
        otherwise have no targeted way to drop it."""
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface(cmd="pytest")]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surface", "browser"],
            self.smm_dir,
            stdin_data=json.dumps({"cmd": None}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("cmd", data["acceptance_surfaces"][0])

    def test_create_rejects_an_unknown_key(self) -> None:
        """`create` is the analyzer's FIRST-write door for surfaces — Step 4
        tells it to inline them here and not to patch them separately in
        create mode, so the check has to hold at this door too."""
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface(cmd="pytest tests/cli")]
        result = run_cli(
            _CLI,
            ["create"],
            self.smm_dir,
            stdin_data=json.dumps(doc),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("cmd", result.stderr)

    def test_create_accepts_the_known_optional_fields(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [
            _surface(command="pytest tests/cli", paths=["src/cli/**"])
        ]
        result = run_cli(
            _CLI,
            ["create"],
            self.smm_dir,
            stdin_data=json.dumps(doc),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(data["acceptance_surfaces"][0]["paths"], ["src/cli/**"])

    def test_generic_edit_field_door_rejects_an_unknown_key(self) -> None:
        """`edit-field acceptance_surfaces` reaches the same writer as the
        named command; without the check keyed on the FIELD it would be a
        silent bypass."""
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-field", "acceptance_surfaces"],
            self.smm_dir,
            stdin_data=json.dumps([_surface(cmd="pytest")]),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("cmd", result.stderr)

    def test_generic_edit_field_door_still_unsets_with_null(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface()]
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-field", "acceptance_surfaces"],
            self.smm_dir,
            stdin_data="null",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("acceptance_surfaces", data)


class TestDeclaredSurfaceFieldsAreVisibleInTheRender(_SMMTestCase):
    """Update mode reads the document through `render` and then REPLACES the
    whole surfaces array. A declared value the render hides is therefore
    deleted on the next analyzer run — it cannot re-emit what it never saw.
    """

    def test_render_shows_paths_and_command(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [
            _surface(command="pytest tests/cli", paths=["src/cli/**"])
        ]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("src/cli/**", result.stdout)
        self.assertIn("pytest tests/cli", result.stdout)

    def test_render_omits_the_rows_when_undeclared(self) -> None:
        doc = valid_doc()
        doc["acceptance_surfaces"] = [_surface()]
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertNotIn("paths:", result.stdout)
        self.assertNotIn("command:", result.stdout)


if __name__ == "__main__":
    unittest.main()
