#!/usr/bin/env python3
"""Tests for xp-work-selection preload: Try items, questions, sprint, intent."""

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import (
    SPRINT_MIXED,
    _IntegrationTestCase,
    _s,
    _sprint_json,
    make_event,
    write_smm_fixture,
)
from event_schema import (
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_QUESTION,
)

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-work-selection"
    / "scripts"
    / "preload.sh"
)

SPRINT_IN_PROGRESS = _sprint_json(
    [
        _s("story-001", "As a user I can log in", "in-progress"),
        _s("story-002", "As a user I can register", "ready"),
    ],
    sprint_id="sprint-001",
    started="2026-04-01",
)

_SMM_WITH_RISKS: dict[str, Any] = dict(
    intent=[("Ship v2", "goal")],
    constraints=[("TDD always", "convention")],
    risks=[
        ("Security gate broken - 41% coverage", "concern", "problem"),
        ("Should we use REST or GraphQL?", "question", "uncertainty"),
    ],
    wisdom=["Commit after green"],
)

_SMM_WITH_INTENT: dict[str, Any] = dict(
    intent=[
        ("Build auth system", "goal"),
        ("Add role-based access", "goal"),
    ],
)


# ===========================================================================
# Preload integration tests
# ===========================================================================


class TestWorkSelectionPreload(_IntegrationTestCase):
    """M1: xp-work-selection preload outputs session data."""

    # Inherits _seed_events from _IntegrationTestCase for writing events.

    def _write_retro(self, tries: list[str]) -> None:
        retro_dir = self.smm_dir / "retrospectives"
        retro_dir.mkdir(exist_ok=True)
        data = {
            "timestamp": "2026-04-05T10:00:00+00:00",
            "keep": [],
            "fix": [],
            "try": [{"content": t} for t in tries],
        }
        (retro_dir / "2026-04-05T10-00-00.json").write_text(json.dumps(data))

    # --- Basic output ---

    def test_outputs_smm_dir(self):
        """Preload always outputs SMM_DIR."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_sets_needs_housekeeping_marker(self):
        """Preload sets .needs-housekeeping so the stop gate activates
        right before housekeeping runs (not at kickoff start)."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / ".needs-housekeeping").exists())

    def test_empty_state_graceful(self):
        """No retro, no SMM, no sprint — exits 0 with minimal output."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)
        self.assertIn("No Active Sprint", result.stdout)

    # --- Try items ---

    def test_shows_try_items(self):
        """Try items from latest retro JSON appear in output."""
        self._write_retro(["Fix gate coverage", "Add lint auto-fix"])
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Previous Try Items", result.stdout)
        self.assertIn("Fix gate coverage", result.stdout)
        self.assertIn("Add lint auto-fix", result.stdout)

    def test_try_items_include_event_refs(self):
        """Try items with event_refs show refs in output for resolution wiring."""
        retro_dir = self.smm_dir / "retrospectives"
        retro_dir.mkdir(exist_ok=True)
        data = {
            "timestamp": "2026-04-05T10:00:00+00:00",
            "keep": [],
            "fix": [],
            "try": [
                {
                    "content": "Fix gate coverage",
                    "event_refs": ["abcd1234-5678-4abc-9def-000000000001"],
                },
                {"content": "No refs item", "event_refs": []},
            ],
        }
        (retro_dir / "2026-04-05T10-00-00.json").write_text(json.dumps(data))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("abcd1234-5678-4abc-9def-000000000001", result.stdout)
        no_refs_line = next(
            line for line in result.stdout.splitlines() if "No refs item" in line
        )
        self.assertNotIn("[refs:", no_refs_line)

    def test_try_items_multiple_event_refs(self):
        """Try items with multiple event_refs show all refs in output."""
        retro_dir = self.smm_dir / "retrospectives"
        retro_dir.mkdir(exist_ok=True)
        data = {
            "timestamp": "2026-04-05T10:00:00+00:00",
            "keep": [],
            "fix": [],
            "try": [
                {
                    "content": "Multi-ref item",
                    "event_refs": [
                        "aaaa1111-2222-4333-8444-555555555555",
                        "bbbb6666-7777-4888-9999-aaaaaaaaaaaa",
                    ],
                },
            ],
        }
        (retro_dir / "2026-04-05T10-00-00.json").write_text(json.dumps(data))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("aaaa1111-2222-4333-8444-555555555555", result.stdout)
        self.assertIn("bbbb6666-7777-4888-9999-aaaaaaaaaaaa", result.stdout)

    def test_no_try_items_when_no_retro(self):
        """No retro dir — no Try Items section."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Previous Try Items", result.stdout)

    def test_no_try_items_when_empty_tries(self):
        """Retro exists but try list is empty — no section."""
        self._write_retro([])
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Previous Try Items", result.stdout)

    # --- Triage sections (from events.jsonl, not Risks pillar) ---

    def test_shows_triage_debts(self):
        """Unresolved debt events appear under Open Debts."""
        events = [make_event(EVENT_TYPE_DEBT, content="Fix auth module")]
        self._seed_events(events)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Open Debts:", result.stdout)
        self.assertIn("Fix auth module", result.stdout)

    def test_shows_triage_concerns(self):
        """Unresolved concern events appear under Open Concerns."""
        events = [make_event(EVENT_TYPE_CONCERN, content="Security gap")]
        self._seed_events(events)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Open Concerns:", result.stdout)
        self.assertIn("Security gap", result.stdout)

    def test_shows_triage_questions(self):
        """Unresolved question events appear under Open Questions."""
        events = [make_event(EVENT_TYPE_QUESTION, content="Use REST?")]
        self._seed_events(events)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Open Questions:", result.stdout)
        self.assertIn("Use REST?", result.stdout)

    def test_no_triage_when_no_events(self):
        """No events — no triage sections."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Open Debts:", result.stdout)
        self.assertNotIn("### Open Concerns:", result.stdout)
        self.assertNotIn("### Open Questions:", result.stdout)

    def test_risks_pillar_no_longer_shown(self):
        """Risks pillar content does NOT appear — replaced by events."""
        write_smm_fixture(self.smm_dir, **_SMM_WITH_RISKS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("## Risks", result.stdout)

    # --- Sprint status ---

    def test_shows_sprint_status_with_ready(self):
        """Sprint with ready stories shows count and titles."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_MIXED)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Sprint Status", result.stdout)
        self.assertIn("Ready: 2", result.stdout)
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)

    def test_no_sprint_shows_no_active(self):
        """No sprint.json — shows No Active Sprint."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No Active Sprint", result.stdout)

    def test_shows_in_progress_count(self):
        """Sprint with in-progress stories shows count."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("In-Progress: 1", result.stdout)

    # --- Customer intent ---

    def test_shows_intent(self):
        """Intent pillar from SMM appears in output."""
        write_smm_fixture(self.smm_dir, **_SMM_WITH_INTENT)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Customer Intent", result.stdout)
        self.assertIn("Build auth system", result.stdout)
        self.assertIn("Add role-based access", result.stdout)

    def test_no_intent_when_no_intent_section(self):
        """SMM with Risks but empty Intent — no Customer Intent heading."""
        write_smm_fixture(
            self.smm_dir,
            risks=[("a risk", "concern", "problem")],
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Customer Intent", result.stdout)


if __name__ == "__main__":
    unittest.main()
