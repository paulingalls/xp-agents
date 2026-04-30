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


# ── edit-branching ─────────────────────────────────────────────


class TestEditBranchingCommand(_SMMTestCase):
    def test_edit_branching_valid(self) -> None:
        _write_doc(self.smm_dir)
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
        _write_doc(self.smm_dir)
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
        doc = _valid_doc()
        doc["branching_strategy"] = {"stage": 0}
        _write_doc(self.smm_dir, doc)
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
        doc = _valid_doc()
        doc["branching_strategy"] = {"stage": 2, "protected_branches": ["main"]}
        _write_doc(self.smm_dir, doc)
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
        doc = _valid_doc()
        doc["acceptance_surfaces"] = [
            {"name": "cli", "signals": ["x"], "status": "covered"}
        ]
        _write_doc(self.smm_dir, doc)
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
        doc = _valid_doc()
        doc["branching_strategy"] = {
            "stage": 2,
            "user_namespace": "paul",
            "protected_branches": ["main"],
            "rationale": "Team project with CI",
        }
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Branching Strategy", result.stdout)
        self.assertIn("Stage 2", result.stdout)
        self.assertIn("paul", result.stdout)
        self.assertIn("main", result.stdout)

    def test_render_omits_when_absent(self) -> None:
        _write_doc(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("Branching Strategy", result.stdout)

    def test_render_shows_integration_branch(self) -> None:
        doc = _valid_doc()
        doc["branching_strategy"] = {
            "stage": 3,
            "integration_branch": "develop",
        }
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertIn("develop", result.stdout)

    def test_section_command_returns_branching(self) -> None:
        doc = _valid_doc()
        doc["branching_strategy"] = {"stage": 1}
        _write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["section", "branching_strategy"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Stage 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
