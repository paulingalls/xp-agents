#!/usr/bin/env python3
"""Tests for the test_layout CLI surface in system_context_cli.

Scope: edit-test-layout / get-test-layout subcommands + the render
section assertion for the new "## Test Layout" block (story-002,
sprint-107). Pre-existing CLI tests live in tests/engine/.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc, valid_test_layout, write_doc
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "system_context_cli.py"


def _read_doc(smm_dir: Path) -> dict:
    return json.loads((smm_dir / SYSTEM_CONTEXT_FILENAME).read_text())


class TestEditTestLayout(_SMMTestCase):
    def test_edit_then_get_roundtrip(self) -> None:
        write_doc(self.smm_dir)
        layout = {"convention": "python_pytest", "overrides": []}
        result = run_cli(
            _CLI,
            ["edit-test-layout"],
            self.smm_dir,
            stdin_data=json.dumps(layout),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_doc(self.smm_dir)["test_layout"], layout)

        got = run_cli(_CLI, ["get-test-layout"], self.smm_dir)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(json.loads(got.stdout), layout)


class TestGetTestLayoutAbsent(_SMMTestCase):
    def test_get_returns_null_when_field_absent(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["get-test-layout"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), None)


class TestEditTestLayoutValidation(_SMMTestCase):
    def test_empty_object_is_rejected_with_hint(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["edit-test-layout"], self.smm_dir, stdin_data="{}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("convention", result.stderr)
        self.assertIn("null", result.stderr)
        # On-disk doc must NOT have grown a test_layout field.
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))

    def test_unknown_convention_is_rejected(self) -> None:
        write_doc(self.smm_dir)
        bad = {"convention": "totally_made_up"}
        result = run_cli(
            _CLI,
            ["edit-test-layout"],
            self.smm_dir,
            stdin_data=json.dumps(bad),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))

    def test_invalid_json_is_rejected(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(
            _CLI, ["edit-test-layout"], self.smm_dir, stdin_data="not json {"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))


class TestEditTestLayoutNullUnsets(_SMMTestCase):
    def test_null_clears_existing_layout(self) -> None:
        doc = valid_doc(test_layout=valid_test_layout())
        write_doc(self.smm_dir, doc)
        self.assertIn("test_layout", _read_doc(self.smm_dir))

        result = run_cli(_CLI, ["edit-test-layout"], self.smm_dir, stdin_data="null")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))

    def test_null_on_already_unset_is_idempotent(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["edit-test-layout"], self.smm_dir, stdin_data="null")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))


class TestRenderTestLayoutSection(_SMMTestCase):
    """Render-section subprocess assertions for the Test Layout block.

    The plan keeps this assertion INSIDE the CLI test file (and inside
    the acceptance command) instead of leaking into a renderer-test
    path outside file_domain.
    """

    def test_render_includes_test_layout_section(self) -> None:
        doc = valid_doc(test_layout=valid_test_layout(convention="python_pytest"))
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Test Layout", result.stdout)
        self.assertIn("python_pytest", result.stdout)

    def test_render_shows_override_count_when_present(self) -> None:
        doc = valid_doc(
            test_layout=valid_test_layout(
                convention="custom",
                overrides=(
                    {
                        "source_pattern": "src/**/*.py",
                        "stem_extractor": "basename_no_ext",
                        "test_glob": "tests/**/test_{stem}.py",
                    },
                ),
            )
        )
        write_doc(self.smm_dir, doc)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Test Layout", result.stdout)
        self.assertIn("custom", result.stdout)
        self.assertIn("1", result.stdout)  # one override rule

    def test_render_omits_when_test_layout_absent(self) -> None:
        write_doc(self.smm_dir)
        result = run_cli(_CLI, ["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("## Test Layout", result.stdout)


class TestCreatePreservesTestLayout(_SMMTestCase):
    def test_create_without_test_layout_preserves_existing(self) -> None:
        existing = valid_doc(test_layout=valid_test_layout(convention="go_native"))
        write_doc(self.smm_dir, existing)

        # Re-create with NO test_layout key in the incoming doc.
        incoming = valid_doc()
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        on_disk = _read_doc(self.smm_dir)
        self.assertEqual(on_disk.get("test_layout"), {"convention": "go_native"})

    def test_create_with_test_layout_null_drops_existing(self) -> None:
        existing = valid_doc(test_layout=valid_test_layout())
        write_doc(self.smm_dir, existing)
        incoming = valid_doc(test_layout=None)
        result = run_cli(
            _CLI, ["create"], self.smm_dir, stdin_data=json.dumps(incoming)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test_layout", _read_doc(self.smm_dir))


if __name__ == "__main__":
    unittest.main()
