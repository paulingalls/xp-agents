#!/usr/bin/env python3
"""Capstone: M6 sprint-verify rerun + close-gate lifecycle, end to end.

Composes the three Milestone-6 seams over a real temp git repo + real SMM
(no mocked boundaries, unlike the per-story unit tests):
- the sprint-wide batch verify + deterministic sprint-verify event
  (verify_acceptance.py --sprint, story-001),
- the sprint-close gate signal (xp-sprint-close preload VERIFY_STATUS,
  story-003),
- the --force-close debt escape (the SKILL's append.sh debt emission).
story-002's sprint-review render is prose-pinned in its own suite.

Pure composition pin: passes when the seams are intact, fails if one breaks.
The prose merge-refusal itself is LLM-driven, so the capstone pins the
deterministic VERIFY_STATUS signal the gate refuses on (mirrors the M5
capstone pinning VERIFY_UNTOUCHED).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from _bases import _PLUGIN_ROOT
from _branching_fixtures import write_system_context
from conftest import _extract_preload_var, _IntegrationTestCase
from event_helpers import events_of_type

_VERIFY = _PLUGIN_ROOT / "scripts" / "verify_acceptance.py"
_CLOSE_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-sprint-close" / "scripts" / "preload.sh"


def _story(story_id: str, *, acceptance_criteria, acceptance_execution=None) -> dict:
    story = {
        "id": story_id,
        "title": f"t-{story_id}",
        "status": "done",
        "dependencies": [],
        "milestone_ref": "",
        "design_sources": "",
        "context": "",
        "file_domain": [],
        "interface_contracts": [],
        "acceptance_criteria": acceptance_criteria,
    }
    if acceptance_execution is not None:
        story["acceptance_execution"] = acceptance_execution
    return story


class TestMilestone06VerifyCloseLifecycle(_IntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        write_system_context(self.smm_dir, stage=2, integration_branch="main")

    def _seed(self, stories: list[dict]) -> None:
        (self.smm_dir / "sprint.json").write_text(
            json.dumps(
                {
                    "sprint_id": "sprint-001",
                    "goal": "g",
                    "started": "2026-05-21",
                    "milestone": "",
                    "stories": stories,
                }
            )
        )

    def _seed_mixed(self) -> None:
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

    def _run_verify_sprint(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_VERIFY), "--sprint", "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
            env=self._env_with_plugin_root(),
            cwd=self.tmpdir,
        )

    def _verify_events(self) -> list[dict]:
        return [
            e
            for e in events_of_type(self._read_events(), _common.SPRINT)
            if (e.get("metadata") or {}).get("action") == "verify"
        ]

    def _close_verify_status(self) -> str | None:
        result = self._run_preload(_CLOSE_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return _extract_preload_var(result.stdout, "VERIFY_STATUS")

    def test_red_lifecycle_matrix_event_and_close_signal(self):
        self._seed_mixed()
        result = self._run_verify_sprint()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Surface-grouped PASS/FAIL matrix.
        self.assertIn("Surface:", result.stdout)
        self.assertIn("[PASS]", result.stdout)
        self.assertIn("[FAIL]", result.stdout)
        # Deterministic red sprint-verify event naming exactly the failing item.
        events = self._verify_events()
        self.assertEqual(len(events), 1, events)
        meta = events[0]["metadata"]
        self.assertEqual(meta["verify_status"], "red")
        self.assertEqual(len(meta["failing"]), 1, meta["failing"])
        self.assertEqual(meta["failing"][0]["command"], "false")
        # The close gate's blocking input.
        self.assertEqual(self._close_verify_status(), "red")

    def test_force_close_records_debt(self):
        self._seed_mixed()
        self._run_verify_sprint()
        # The SKILL Step 0 force-close path emits a debt event with the failing
        # items; drive its documented append.sh command directly.
        result = self._run_append(
            "--type",
            "debt",
            "--agent",
            "xp-sprint-close",
            "--content",
            "Force-close deadline ship: merged sprint with red verify items: false",
            "--files",
            json.dumps([str(self.smm_dir / "sprint.json")]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        debts = events_of_type(self._read_events(), _common.DEBT)
        self.assertEqual(len(debts), 1)
        self.assertIn("Force-close", debts[0]["content"])

    def test_all_string_skips_and_does_not_block(self):
        self._seed(
            [
                _story("story-001", acceptance_criteria=["manual 1", "E2E: manual 2"]),
                _story("story-002", acceptance_criteria=["manual 3"]),
            ]
        )
        result = self._run_verify_sprint()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no verify-bearing acceptance to rerun", result.stdout)
        self.assertEqual(self._verify_events(), [])
        # No verify event → gate reads none → close not blocked.
        self.assertEqual(self._close_verify_status(), "none")

    def test_e2e_full_lifecycle(self):
        # red rerun → matrix + red event → close signal red → force-close debt.
        self._seed_mixed()
        result = self._run_verify_sprint()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[FAIL]", result.stdout)
        self.assertEqual(self._verify_events()[0]["metadata"]["verify_status"], "red")
        self.assertEqual(self._close_verify_status(), "red")
        self._run_append(
            "--type",
            "debt",
            "--agent",
            "xp-sprint-close",
            "--content",
            "Force-close override: red verify items: false",
            "--files",
            json.dumps([str(self.smm_dir / "sprint.json")]),
        )
        self.assertEqual(len(events_of_type(self._read_events(), _common.DEBT)), 1)


if __name__ == "__main__":
    unittest.main()
