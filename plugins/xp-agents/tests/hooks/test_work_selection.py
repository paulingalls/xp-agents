#!/usr/bin/env python3
"""Tests for xp-work-selection preload: Try items, questions, sprint, intent."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-work-selection"
    / "scripts"
    / "preload.sh"
)

SPRINT_MIXED = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: As a user I can register
- **Size:** S
- **Status:** ready
- **Dependencies:** none

### story-003: As an admin I can list users
- **Size:** L
- **Status:** ready
- **Dependencies:** story-002
"""

SPRINT_IN_PROGRESS = """\
# Sprint: Build auth

- **Sprint ID:** sprint-001
- **Started:** 2026-04-01

## Stories

### story-001: As a user I can log in
- **Size:** M
- **Status:** in-progress
- **Dependencies:** none

### story-002: As a user I can register
- **Size:** S
- **Status:** ready
- **Dependencies:** none
"""

SMM_WITH_RISKS = """\
# Shared Mental Model

## Intent
- 📋 Ship v2

## Constraints
- TDD always

## Risks
- 🔴 Security gate broken — 41% coverage
- Should we use REST or GraphQL?

## Wisdom
- Commit after green
"""

SMM_WITH_INTENT = """\
# Shared Mental Model

## Intent
- 📋 Build auth system
- 📋 Add role-based access
"""


# ===========================================================================
# Preload integration tests
# ===========================================================================


class TestWorkSelectionPreload(_IntegrationTestCase):
    """M1: xp-work-selection preload outputs session data."""

    def _run_preload(self) -> subprocess.CompletedProcess:
        if not _PRELOAD_SCRIPT.is_file():
            self.skipTest("preload.sh not yet created")
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)
        return subprocess.run(
            ["bash", str(_PRELOAD_SCRIPT)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

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
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_empty_state_graceful(self):
        """No retro, no SMM, no sprint — exits 0 with minimal output."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)
        self.assertIn("No Active Sprint", result.stdout)

    # --- Try items ---

    def test_shows_try_items(self):
        """Try items from latest retro JSON appear in output."""
        self._write_retro(["Fix gate coverage", "Add lint auto-fix"])
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Previous Try Items", result.stdout)
        self.assertIn("Fix gate coverage", result.stdout)
        self.assertIn("Add lint auto-fix", result.stdout)

    def test_no_try_items_when_no_retro(self):
        """No retro dir — no Try Items section."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Previous Try Items", result.stdout)

    def test_no_try_items_when_empty_tries(self):
        """Retro exists but try list is empty — no section."""
        self._write_retro([])
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Previous Try Items", result.stdout)

    # --- Open questions (from SMM Risks pillar) ---

    def test_shows_open_questions(self):
        """Risks pillar content appears under Open Questions."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(SMM_WITH_RISKS)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Open Questions", result.stdout)
        self.assertIn("Security gate broken", result.stdout)

    def test_no_questions_when_no_risks(self):
        """SMM without Risks section — no Open Questions."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n\n## Intent\n- goal\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Open Questions", result.stdout)

    # --- Sprint status ---

    def test_shows_sprint_status_with_ready(self):
        """Sprint with ready stories shows count and titles."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_MIXED)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Sprint Status", result.stdout)
        self.assertIn("Ready: 2", result.stdout)
        self.assertIn("story-002", result.stdout)
        self.assertIn("story-003", result.stdout)

    def test_no_sprint_shows_no_active(self):
        """No sprint.md — shows No Active Sprint."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No Active Sprint", result.stdout)

    def test_shows_in_progress_count(self):
        """Sprint with in-progress stories shows count."""
        (self.smm_dir / "sprint.md").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("In-Progress: 1", result.stdout)

    # --- Customer intent ---

    def test_shows_intent(self):
        """Intent pillar from SMM appears in output."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(SMM_WITH_INTENT)
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### Customer Intent", result.stdout)
        self.assertIn("Build auth system", result.stdout)
        self.assertIn("Add role-based access", result.stdout)

    def test_no_intent_when_no_intent_section(self):
        """SMM without Intent section — no Customer Intent."""
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n\n## Risks\n- a risk\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### Customer Intent", result.stdout)


if __name__ == "__main__":
    unittest.main()
