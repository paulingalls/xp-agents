#!/usr/bin/env python3
"""Integration tests for skills/xp-security-triage/scripts/mark_triaged.py.

Sprint-041 / story-002 — verifies the script appends a status event with
metadata.action=security_triage_started so retro_metrics can detect triage
runs without regex-matching content.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase
from event_schema import event_action

_MARK_TRIAGED = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-security-triage"
    / "scripts"
    / "mark_triaged.py"
)


class TestMarkTriagedAction(_IntegrationTestCase):
    """mark_triaged.py emits an action-tagged event for the triage start."""

    def _run_mark_triaged(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_MARK_TRIAGED), "--smm-dir", str(self.smm_dir)],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )

    def test_emits_status_event_with_security_triage_started_action(self):
        result = self._run_mark_triaged()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        events = self._read_events()
        triage_started = [
            e for e in events if event_action(e) == "security_triage_started"
        ]
        self.assertEqual(len(triage_started), 1)
        self.assertEqual(triage_started[0]["type"], "status")
        # agent_id is teammate-resolved attribution per the agent-id-semantics
        # ADR; in this integration harness the cwd is a non-worktree tmpdir
        # so resolve_agent_id_from_cwd returns "main".
        self.assertEqual(triage_started[0]["agent_id"], "main")


if __name__ == "__main__":
    unittest.main()
