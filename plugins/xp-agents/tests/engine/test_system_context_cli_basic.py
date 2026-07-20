#!/usr/bin/env python3
"""Tests for system_context_cli.py: exists/validate/create commands.

Split from test_system_context_cli.py (over the 500-line cap); render,
section, and mutation commands live in the render/additions siblings.
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


if __name__ == "__main__":
    unittest.main()
