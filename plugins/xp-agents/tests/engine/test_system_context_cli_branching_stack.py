#!/usr/bin/env python3
"""Tests for system_context_cli.py: stack-field and convention commands.

Split from test_system_context_cli_branching.py (over the 500-line cap);
branching_strategy field commands live in the
test_system_context_cli_branching_fields.py sibling.
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


if __name__ == "__main__":
    unittest.main()
