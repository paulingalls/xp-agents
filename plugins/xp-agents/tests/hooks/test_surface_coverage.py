#!/usr/bin/env python3
"""Tests for surface_coverage.py — uncovered touched-surface detection.

uncovered_touched_surfaces checks a milestone's surfaces_touched against
the project's acceptance_surfaces, returning the touched names whose status
is not 'covered' (a 'gap' surface, or a name absent from acceptance_surfaces
entirely). Powers /xp-sprint-start's per-surface coverage concern.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _cli_helpers import make_milestone_dict, make_plan_dict
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "scripts" / "surface_coverage.py"


def _surfaces(*pairs: tuple[str, str]) -> list[dict]:
    return [{"name": n, "signals": ["x"], "status": s} for n, s in pairs]


class TestUncoveredTouchedSurfaces(_SMMTestCase):
    def _write_context(self, surfaces: list[dict]) -> None:
        doc = valid_doc(acceptance_surfaces=surfaces)
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(json.dumps(doc))

    def test_returns_only_uncovered_touched(self):
        import surface_coverage

        self._write_context(_surfaces(("api", "gap"), ("cli", "covered")))
        milestone = {"surfaces_touched": ["api", "cli"]}
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces(milestone, self.smm_dir),
            ["api"],
        )

    def test_all_covered_returns_empty(self):
        import surface_coverage

        self._write_context(_surfaces(("api", "covered"), ("cli", "covered")))
        milestone = {"surfaces_touched": ["api", "cli"]}
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces(milestone, self.smm_dir),
            [],
        )

    def test_missing_surfaces_touched_returns_empty(self):
        import surface_coverage

        self._write_context(_surfaces(("api", "gap")))
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces({}, self.smm_dir),
            [],
        )

    def test_unknown_touched_surface_counts_as_uncovered(self):
        import surface_coverage

        self._write_context(_surfaces(("cli", "covered")))
        milestone = {"surfaces_touched": ["cli", "ghost"]}
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces(milestone, self.smm_dir),
            ["ghost"],
        )

    def test_order_preserved(self):
        import surface_coverage

        self._write_context(_surfaces(("a", "gap"), ("b", "covered"), ("c", "gap")))
        milestone = {"surfaces_touched": ["c", "b", "a"]}
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces(milestone, self.smm_dir),
            ["c", "a"],
        )


class TestUncoveredCli(_SMMTestCase):
    def _seed(self, surfaces: list[dict], surfaces_touched: list[str]) -> None:
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=surfaces))
        )
        plan = make_plan_dict(
            milestones=[
                make_milestone_dict(number=3, surfaces_touched=surfaces_touched)
            ]
        )
        import execution_plan_store

        execution_plan_store.save_plan(self.smm_dir, plan)

    def test_uncovered_for_milestone_prints_json_array(self):
        self._seed(_surfaces(("api", "gap"), ("cli", "covered")), ["api", "cli"])
        result = run_cli(_CLI, ["uncovered", "--milestone", "3"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["api"])

    def test_uncovered_all_covered_prints_empty_array(self):
        self._seed(_surfaces(("cli", "covered")), ["cli"])
        result = run_cli(_CLI, ["uncovered", "--milestone", "3"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
