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

from _system_context_fixtures import write_doc
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


if __name__ == "__main__":
    unittest.main()
