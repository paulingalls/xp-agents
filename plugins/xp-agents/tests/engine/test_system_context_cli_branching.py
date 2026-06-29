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


# ── get-stack-field ────────────────────────────────────────────


class TestGetStackFieldCommand(_SMMTestCase):
    """get-stack-field is the read-only counterpart to edit-stack-field.
    Always exits 0 — empty stdout is the canonical "field not
    configured" signal so shell callers can use it in `KEY=$(...)`
    assignments without exit-code branching. Used by the close-skill
    preloads' find_test_command wrapper.
    """

    def test_get_stack_field_returns_value(self) -> None:
        doc = valid_doc()
        doc["stack"]["test_command"] = "pytest -n auto"
        write_doc(self.smm_dir, doc=doc)
        result = run_cli(_CLI, ["get-stack-field", "test_command"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "pytest -n auto")

    def test_get_stack_field_empty_when_unset(self) -> None:
        # When the field is not configured, the CLI must exit 0 with
        # empty stdout — shell callers expect to plug the result into
        # KEY=$(...) without checking exit codes.
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["get-stack-field", "test_command"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_get_stack_field_empty_when_no_system_context(self) -> None:
        # Graceful for repos that haven't run /xp-system-context yet.
        # Exit 0 + empty so close-skill preloads work pre-config.
        result = run_cli(_CLI, ["get-stack-field", "test_command"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_get_stack_field_nonzero_when_system_context_malformed(self) -> None:
        # Schema validation runs on load — a hand-edited file with a
        # non-string test_command surfaces as a load-time ValueError.
        # The CLI exits non-zero with a traceback; the shell wrapper
        # `find_test_command` traps that via `2>/dev/null || echo ""`
        # and the close-skill preload sees TEST_COMMAND= (empty),
        # falling through to the discovery hint. Pin the CLI side of
        # the contract: malformed files DON'T silently masquerade as
        # "unset" at the CLI layer — that translation happens in shell.
        doc = valid_doc()
        doc["stack"]["test_command"] = ["pytest", "-n", "auto"]
        write_doc(self.smm_dir, doc=doc)
        result = run_cli(_CLI, ["get-stack-field", "test_command"], self.smm_dir)
        self.assertNotEqual(
            result.returncode,
            0,
            "malformed system_context.json must surface as non-zero exit "
            "from the CLI; the shell wrapper translates that to empty",
        )


# ── add-convention ─────────────────────────────────────────────


class TestAddConventionCommand(_SMMTestCase):
    """add-convention closes the asymmetry where add-module,
    add-principle, and add-acceptance-surface all exist for list
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
