#!/usr/bin/env python3
"""Tests for verify_acceptance.py --sprint batch mode + --query-verify-status.

Milestone 6 reruns every verify-bearing acceptance item across the sprint and
gates close on green. story-001 builds the primitive:

- ``--sprint`` iterates all stories, gathers per-AC verify objects (by surface)
  plus story-level acceptance_execution, runs each command, prints a
  surface-grouped PASS/FAIL matrix, and emits a deterministic
  ``sprint``/``action=verify`` event whose metadata carries verify_status +
  the failing items.
- ``--query-verify-status`` reads the last such event for the current sprint
  and reports red/green/none (the reader the sprint-close gate consumes).

The green/red signal is script-emitted (not reviewer prose) so the close gate
reads a deterministic event and never recomputes.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
import verify_acceptance
from _bases import _HookTestCase
from conftest import make_sprint_dict, run_cli

_VERIFY_ACCEPTANCE = (
    Path(__file__).parent.parent.parent / "scripts" / "verify_acceptance.py"
)


def _story(story_id: str, *, acceptance_criteria, acceptance_execution=None) -> dict:
    story = {
        "id": story_id,
        "title": f"Story {story_id}",
        "status": "done",
        "dependencies": [],
        "milestone_ref": "",
        "design_sources": "",
        "context": "ctx",
        "file_domain": [f"src/{story_id}.py — x"],
        "interface_contracts": [],
        "acceptance_criteria": acceptance_criteria,
    }
    if acceptance_execution is not None:
        story["acceptance_execution"] = acceptance_execution
    return story


class _SprintCLITestCase(_HookTestCase):
    def _seed(self, stories: list[dict]) -> None:
        sprint = make_sprint_dict(sprint_id="sprint-093", stories=stories)
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _run(self, *args: str):
        return run_cli(_VERIFY_ACCEPTANCE, list(args), self.smm_dir)

    def _verify_events(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("type") == "sprint"
            and (e.get("metadata") or {}).get("action") == "verify"
        ]


class TestSprintBatchMatrix(_SprintCLITestCase):
    def test_matrix_grouped_by_surface_with_pass_fail(self):
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        "a manual string AC",
                        {"description": "ok", "surface": "cli", "command": "true"},
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
                _story(
                    "story-002",
                    acceptance_criteria=["string only"],
                    acceptance_execution={"type": "pytest", "command": "true"},
                ),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        # surface buckets: the "cli" per-AC items and the story-level "(story)"
        self.assertIn("cli", out)
        self.assertIn("(story)", out)
        self.assertIn("[PASS]", out)
        self.assertIn("[FAIL]", out)
        self.assertIn("story-001", out)
        self.assertIn("story-002", out)


class TestAllStringSkip(_SprintCLITestCase):
    def test_no_verify_items_emits_no_event_exit_0(self):
        self._seed(
            [
                _story("story-001", acceptance_criteria=["manual 1", "E2E: manual 2"]),
                _story("story-002", acceptance_criteria=["manual 3"]),
            ]
        )
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._verify_events(), [])

    def test_query_status_none_when_no_event(self):
        self._seed([_story("story-001", acceptance_criteria=["manual"])])
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("none", result.stdout)


class TestMixedRedEventAndQuery(_SprintCLITestCase):
    def _seed_mixed(self) -> None:
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        "manual",
                        {"description": "ok", "surface": "cli", "command": "true"},
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
                _story(
                    "story-002",
                    acceptance_criteria=["string"],
                    acceptance_execution={"type": "pytest", "command": "true"},
                ),
            ]
        )

    def test_sprint_emits_red_event_listing_exact_failing_item(self):
        self._seed_mixed()
        result = self._run("--sprint")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(meta["verify_status"], "red")
        failing = meta["failing"]
        self.assertEqual(len(failing), 1, failing)
        item = failing[0]
        self.assertEqual(item["story"], "story-001")
        self.assertEqual(item["command"], "false")
        self.assertNotEqual(item["returncode"], 0)
        self.assertEqual(item["surface"], "cli")

    def test_query_status_reports_red_after_red_sprint(self):
        self._seed_mixed()
        self._run("--sprint")
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("red", result.stdout)
        self.assertIn("false", result.stdout)


class TestCommandTimeout(_SprintCLITestCase):
    def test_hung_command_marked_failed_with_timeout_output(self):
        # The --sprint path runs unattended at sprint-close; a hung acceptance
        # command must convert to an attributable red, never block forever.
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "h", "surface": "cli", "command": "sleep 5"},
                    ],
                ),
            ]
        )
        result = run_cli(
            _VERIFY_ACCEPTANCE,
            ["--sprint"],
            self.smm_dir,
            extra_env={"VERIFY_CMD_TIMEOUT_S": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        failing = events[0]["metadata"]["failing"]
        self.assertEqual(len(failing), 1, failing)
        self.assertNotEqual(failing[0]["returncode"], 0)
        self.assertIn("timed out", failing[0]["output"])


class TestEmitConfirmation(_SprintCLITestCase):
    def test_dropped_event_surfaces_error_not_silent_green(self):
        # append_safe swallows validation errors + lock timeouts. If the verify
        # event silently fails to land, --query-verify-status would read it as
        # green and pass a red sprint. _run_sprint must fail loud instead.
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "bad", "surface": "cli", "command": "false"},
                    ],
                ),
            ]
        )
        # Replace append_safe with a no-op so the verify event never lands.
        with patch.object(verify_acceptance._common, "append_safe"):
            rc = verify_acceptance._run_sprint(self.smm_dir)
        self.assertEqual(rc, verify_acceptance._EXIT_ERROR)


class TestQueryStatusGreen(_SprintCLITestCase):
    def test_query_status_green_when_all_pass(self):
        self._seed(
            [
                _story(
                    "story-001",
                    acceptance_criteria=[
                        {"description": "ok", "surface": "cli", "command": "true"},
                    ],
                ),
            ]
        )
        self._run("--sprint")
        result = self._run("--query-verify-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("green", result.stdout)


if __name__ == "__main__":
    unittest.main()
