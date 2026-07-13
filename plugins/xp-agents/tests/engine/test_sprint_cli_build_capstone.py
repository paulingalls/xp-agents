#!/usr/bin/env python3
"""Tests for the sprint CLI's `build-capstone` subcommand.

Split out of test_sprint_cli_mutate.py (story-015, which pushed it past the
500-line cap by adding harness-resolution coverage) — mirrors the
test_sprint_cli_create.py precedent from story-005. TestBuildCapstoneCommand
moved here unchanged.

Covers acceptance_execution.type resolution: an explicit --harness always
wins; otherwise the type is resolved from system_context's
acceptance_surfaces for the capstone's own --surfaces (a single agreed
harness wins, disagreement or absence degrades to a placeholder), and a
missing/corrupt/symlinked system_context.json degrades the same way without
raising. See sprint_cli_mutate._resolve_capstone_harness.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from conftest import (
    _SMMTestCase,
    run_cli,
)
from conftest import (
    make_sprint_dict as _make_sprint,
)
from conftest import (
    make_story_dict as _make_story,
)
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = Path(__file__).parent.parent.parent / "smm" / "sprint_cli.py"


class TestBuildCapstoneCommand(_SMMTestCase):
    def _run(self, extra):
        return run_cli(_CLI, ["build-capstone", *extra], self.smm_dir)

    def test_prints_ready_capstone_json(self):
        result = self._run(
            [
                "--milestone",
                "Milestone 3: surface-coverage",
                "--surfaces",
                "cli,sdk",
                "--depends-on",
                "story-001,story-002",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["id"], "story-006")
        self.assertEqual(story["status"], "ready")
        self.assertTrue(story["title"].startswith("Capstone:"))
        self.assertEqual(story["dependencies"], ["story-001", "story-002"])
        surfaces = {
            a["surface"] for a in story["acceptance_criteria"] if isinstance(a, dict)
        }
        self.assertEqual(surfaces, {"cli", "sdk"})

    def test_output_pipes_into_add_story(self):
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(_make_sprint(stories=[_make_story(id="story-001")]))
        )
        built = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--depends-on",
                "story-001",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(built.returncode, 0, built.stderr)
        added = run_cli(_CLI, ["add-story"], self.smm_dir, stdin_data=built.stdout)
        self.assertEqual(added.returncode, 0, added.stderr)

    def _seed_surfaces(self, surfaces):
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=surfaces))
        )

    def test_no_harness_flag_resolves_single_surface_harness(self):
        # The real bug: a Go/Rust/etc. project's declared harness must flow
        # through automatically — no caller should have to know to pass
        # --harness explicitly for the default case to be correct.
        self._seed_surfaces(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "harness": "go_test",
                    "status": "covered",
                }
            ]
        )
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["acceptance_execution"]["type"], "go_test")

    def test_polyglot_surfaces_disagree_degrades_to_placeholder(self):
        # A TS surface on vitest and a Python surface on pytest is a
        # legitimate disagreement — the fix must not strand exactly the
        # cross-language projects it exists to serve by picking one.
        self._seed_surfaces(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "harness": "go_test",
                    "status": "covered",
                },
                {
                    "name": "api",
                    "signals": ["x"],
                    "harness": "rust_cargo",
                    "status": "covered",
                },
            ]
        )
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli,api",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(
            story["acceptance_execution"]["type"], "<implementer fills: test harness>"
        )

    def test_polyglot_capstone_spanning_one_surface_resolves_that_harness(self):
        # The other direction of the polyglot case, and the one that pins the
        # story's whole point: the project is polyglot (Go + Rust) but THIS
        # capstone spans only the Go surface, so it must resolve go_test.
        # Resolving over every surface the PROJECT declares (rather than the
        # ones the capstone spans) would see two harnesses, degrade to a
        # placeholder, and strand every polyglot repo — the exact users this
        # story exists for. Without this test that regression is green: the
        # disagree/dogfood tests span every surface they seed, so they cannot
        # tell the two implementations apart.
        self._seed_surfaces(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "harness": "go_test",
                    "status": "covered",
                },
                {
                    "name": "api",
                    "signals": ["x"],
                    "harness": "rust_cargo",
                    "status": "covered",
                },
            ]
        )
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["acceptance_execution"]["type"], "go_test")

    def test_surface_declaring_no_harness_degrades_to_placeholder(self):
        # `harness` is optional in the acceptance_surfaces schema
        # (system_context_entry_validators: `if "harness" in entry`), so a
        # declared-but-harnessless surface is a legitimate shape, not a
        # corrupt one. It must degrade, never KeyError.
        self._seed_surfaces([{"name": "cli", "signals": ["x"], "status": "covered"}])
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(
            story["acceptance_execution"]["type"], "<implementer fills: test harness>"
        )

    def test_explicit_harness_wins_over_resolution(self):
        self._seed_surfaces(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "harness": "go_test",
                    "status": "covered",
                }
            ]
        )
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
                "--harness",
                "pytest",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["acceptance_execution"]["type"], "pytest")

    def test_missing_system_context_degrades_to_placeholder(self):
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(
            story["acceptance_execution"]["type"], "<implementer fills: test harness>"
        )

    def test_corrupt_system_context_degrades_and_warns_not_raises(self):
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text("{not valid json")
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(
            story["acceptance_execution"]["type"], "<implementer fills: test harness>"
        )
        self.assertIn("WARN", result.stderr)

    def test_symlinked_system_context_degrades_and_warns_not_raises(self):
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(valid_doc()))
        link = self.smm_dir / SYSTEM_CONTEXT_FILENAME
        link.symlink_to(real)
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(
            story["acceptance_execution"]["type"], "<implementer fills: test harness>"
        )
        self.assertIn("WARN", result.stderr)

    def test_dogfood_this_repos_surfaces_resolve_unittest(self):
        # Mirrors this repo's own declared acceptance_surfaces (cli +
        # automation, both "unittest") — our own capstone must not get
        # "pytest".
        self._seed_surfaces(
            [
                {
                    "name": "cli",
                    "signals": ["x"],
                    "harness": "unittest",
                    "status": "covered",
                },
                {
                    "name": "automation",
                    "signals": ["x"],
                    "harness": "unittest",
                    "status": "covered",
                },
            ]
        )
        result = self._run(
            [
                "--milestone",
                "Milestone 3",
                "--surfaces",
                "cli,automation",
                "--story-id",
                "story-006",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        story = json.loads(result.stdout)
        self.assertEqual(story["acceptance_execution"]["type"], "unittest")


if __name__ == "__main__":
    unittest.main()
