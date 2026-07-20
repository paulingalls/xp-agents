#!/usr/bin/env python3
"""Tests for system_context_cli.py: branching_strategy field commands.

Split from test_system_context_cli_branching.py (over the 500-line cap);
stack-field and add-convention commands live in the
test_system_context_cli_branching_stack.py sibling.
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
        # _cmd_edit_field's generalized null-unset hint fires for any
        # _OPTIONAL_TOP_LEVEL_FIELDS member; pin it for branching_strategy
        # so a future regression re-gating on `name == "test_layout"` is
        # caught by THIS test rather than a transitive test_layout test.
        self.assertIn("null", result.stderr)

    def test_edit_acceptance_surfaces_invalid_payload_emits_null_hint(self) -> None:
        # Sister of test_edit_branching_invalid_stage — pins the generalized
        # null-unset hint for the acceptance_surfaces branch of
        # _OPTIONAL_TOP_LEVEL_FIELDS. acceptance_surfaces must be a list;
        # a dict fails schema validation at save time.
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI,
            ["edit-acceptance-surfaces"],
            self.smm_dir,
            stdin_data=json.dumps({"not": "a list"}),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Validation error", result.stderr)
        self.assertIn("null", result.stderr)

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


# ── edit-branching-field / get-branching-field ─────────────────


class TestEditBranchingFieldCommand(_SMMTestCase):
    """edit-branching-field is the affordance for setting nested
    branching_strategy fields (stage_prompt_dismissed_at, rationale,
    user_namespace, etc.) without rewriting the entire branching
    strategy via edit-branching. Mirrors edit-stack-field.
    """

    def test_sets_stage_prompt_dismissed_at(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 0})
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
            stdin_data='"2026-05-04T17:30:00+00:00"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertEqual(
            data["branching_strategy"]["stage_prompt_dismissed_at"],
            "2026-05-04T17:30:00+00:00",
        )

    def test_preserves_other_branching_fields(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "user_namespace": "paul",
                "rationale": "explicit Stage 0 for solo prototyping",
            }
        )
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
            stdin_data='"2026-05-04T17:30:00+00:00"',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        bs = data["branching_strategy"]
        self.assertEqual(bs["stage"], 0)
        self.assertEqual(bs["user_namespace"], "paul")
        self.assertEqual(bs["rationale"], "explicit Stage 0 for solo prototyping")
        self.assertEqual(bs["stage_prompt_dismissed_at"], "2026-05-04T17:30:00+00:00")

    def test_null_clears_field(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "stage_prompt_dismissed_at": "2026-05-04T17:30:00+00:00",
            }
        )
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
            stdin_data="null",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())
        self.assertNotIn("stage_prompt_dismissed_at", data["branching_strategy"])

    def test_validates_iso_format(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 0})
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["edit-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
            stdin_data='"not a timestamp"',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Validation error", result.stderr)


class TestGetBranchingFieldCommand(_SMMTestCase):
    """Read-only counterpart to edit-branching-field. Always exits 0;
    empty stdout is the canonical "not set" signal so shell callers can
    plug the value into KEY=$(...) without exit-code branching.
    """

    def test_returns_value(self) -> None:
        doc = valid_doc(
            branching_strategy={
                "stage": 0,
                "stage_prompt_dismissed_at": "2026-05-04T17:30:00+00:00",
            }
        )
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["get-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2026-05-04T17:30:00+00:00")

    def test_empty_when_unset(self) -> None:
        doc = valid_doc(branching_strategy={"stage": 0})
        write_doc(self.smm_dir, doc)
        result = run_cli(
            _CLI,
            ["get-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_empty_when_no_system_context(self) -> None:
        result = run_cli(
            _CLI,
            ["get-branching-field", "stage_prompt_dismissed_at"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
