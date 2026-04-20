#!/usr/bin/env python3
"""E2E tests for xp-quality-review pre-commit probe + dedup.

Covers the sprint-007 M3 feature:
- probe_candidates.py drops the REVIEW_FINGERPRINT marker + emits a
  resolves_probe_shown status event when staged files touch an open concern.
- bash_post_tool._handle_commit consumes the marker on the subsequent
  commit and suppresses the duplicate post-commit nudge + status event
  (the dedup that closes the double-counting concern).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from conftest import _IntegrationTestCase, make_event


class TestQualityReviewProbeE2E(_IntegrationTestCase):
    _PROBE_SCRIPT = (
        _PLUGIN_ROOT
        / "skills"
        / "xp-quality-review"
        / "scripts"
        / "probe_candidates.py"
    )

    def _run_probe_script(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "python3",
                str(self._PROBE_SCRIPT),
                "--smm-dir",
                str(self.smm_dir),
                "--cwd",
                str(self.tmpdir),
            ],
            capture_output=True,
            text=True,
            env=self._test_env,
            cwd=self.tmpdir,
        )

    def test_probe_script_drops_marker_and_status_event(self):
        concern = make_event(
            "concern",
            id="abc123def456",
            content="scripts/auth.py leaks tokens",
            files=["scripts/auth.py"],
            severity="medium",
        )
        self._seed_events([concern])

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "auth.py").write_text("print('auth')\n")
        subprocess.run(
            ["git", "add", "scripts/auth.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        result = self._run_probe_script()
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # Marker dropped (agent_id defaults to "main" in a non-worktree cwd)
        marker_file = self.smm_dir / ".review-fingerprint-main"
        self.assertTrue(marker_file.exists(), msg=result.stderr)
        marker_data = json.loads(marker_file.read_text())
        self.assertIn("fingerprint", marker_data)
        self.assertEqual(marker_data["candidate_ids"], ["abc123def456"])

        # Status event emitted for retro metric pairing
        events = self._read_events()
        probes = [
            e
            for e in events
            if e.get("type") == "status"
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["metadata"]["probe_candidates"], ["abc123def456"])

        # stdout surfaces candidate id + trailer guidance for the skill to echo
        self.assertIn("abc123def456", result.stdout)
        self.assertIn("Resolves-Event: <event-id>", result.stdout)

    def test_probe_then_commit_suppresses_duplicate_nudge(self):
        concern = make_event(
            "concern",
            id="deadbeefcafe",
            content="scripts/auth.py leaks",
            files=["scripts/auth.py"],
            severity="medium",
        )
        self._seed_events([concern])

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "auth.py").write_text("print('auth')\n")
        subprocess.run(
            ["git", "add", "scripts/auth.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        probe_result = self._run_probe_script()
        self.assertEqual(probe_result.returncode, 0, msg=probe_result.stderr)

        subprocess.run(
            ["git", "commit", "-m", "Fix auth"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        commit_result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Fix auth'"},
                "tool_response": {"stdout": "[main abc1234] Fix auth\n 1 file changed"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(commit_result.returncode, 0, msg=commit_result.stderr)

        # Dedup: no additionalContext nudge on stdout
        stdout = commit_result.stdout.strip()
        if stdout:
            output = json.loads(stdout)
            ctx = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertNotIn("Auto-link nudge", ctx)

        # Exactly ONE resolves_probe_shown — from pre-commit probe, NOT
        # duplicated post-commit (this is the double-counting guard).
        events = self._read_events()
        probes = [
            e
            for e in events
            if e.get("type") == "status"
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]
        self.assertEqual(len(probes), 1)

        # Marker was consumed post-commit
        self.assertFalse((self.smm_dir / ".review-fingerprint-main").exists())


if __name__ == "__main__":
    unittest.main()
