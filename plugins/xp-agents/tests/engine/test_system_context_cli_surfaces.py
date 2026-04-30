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


if __name__ == "__main__":
    unittest.main()
