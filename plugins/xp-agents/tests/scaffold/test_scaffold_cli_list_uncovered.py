#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — list-uncovered subcommand.

list-uncovered returns the acceptance_surfaces whose status != "covered",
each annotated with canonical_tools, for the SKILL.md multi-surface loop.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _helpers import valid_system_context
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


class TestListUncovered(_SMMTestCase):
    def _write_surfaces(self, surfaces: list[dict]) -> None:
        ctx = valid_system_context(surfaces=surfaces)
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    def _run(self):
        return run_cli(
            _CLI,
            ["list-uncovered", "--repo-root", str(self.smm_dir)],
            self.smm_dir,
        )

    def test_empty_smm_returns_empty_array(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_filters_to_uncovered_only(self) -> None:
        self._write_surfaces(
            [
                {"name": "cli", "signals": ["bin"], "status": "covered"},
                {"name": "sdk", "signals": ["lib"], "status": "covered"},
                {
                    "name": "browser",
                    "signals": ["next.js"],
                    "harness": "playwright",
                    "status": "gap",
                },
            ]
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "browser")

    def test_entry_has_required_keys(self) -> None:
        self._write_surfaces(
            [
                {
                    "name": "browser",
                    "signals": ["next.js"],
                    "harness": "playwright",
                    "status": "gap",
                },
            ]
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads(result.stdout)[0]
        for key in (
            "name",
            "status",
            "harness",
            "canonical_tools",
            "has_tooling",
            "tool_name",
        ):
            self.assertIn(key, entry)

    def test_all_covered_returns_empty_array(self) -> None:
        self._write_surfaces(
            [
                {"name": "cli", "signals": ["bin"], "status": "covered"},
                {"name": "sdk", "signals": ["lib"], "status": "covered"},
            ]
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_canonical_tools_populated_for_known_surface(self) -> None:
        self._write_surfaces(
            [
                {
                    "name": "browser",
                    "signals": ["next.js"],
                    "harness": "playwright",
                    "status": "gap",
                },
            ]
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = json.loads(result.stdout)[0]
        self.assertIn("playwright", entry["canonical_tools"])


if __name__ == "__main__":
    unittest.main()
