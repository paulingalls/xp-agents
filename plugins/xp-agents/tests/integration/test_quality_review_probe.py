#!/usr/bin/env python3
"""E2E tests for xp-quality-review pre-commit probe.

Covers probe_candidates.py: surfaces open concerns whose files intersect
staged changes so the quality-review subagent sees them before the commit.
"""

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

    def test_probe_script_surfaces_matching_concerns(self):
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
        self.assertIn("abc123def456", result.stdout)

    def test_probe_then_commit_emits_probe_event(self):
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

        # Post-commit probe event emitted for metrics.
        events = self._read_events()
        probes = [
            e
            for e in events
            if e.get("type") == "status"
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]
        self.assertEqual(len(probes), 1)

    def test_probe_finds_unstaged_modified_files(self):
        """Probe should detect concerns matching unstaged (not git-added) files."""
        concern = make_event(
            "concern",
            id="unstaged12345",
            content="scripts/auth.py leaks tokens",
            files=["scripts/auth.py"],
            severity="medium",
        )
        self._seed_events([concern])

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "auth.py").write_text("print('v1')\n")
        subprocess.run(
            ["git", "add", "scripts/auth.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        (self.tmpdir / "scripts" / "auth.py").write_text("print('v2')\n")

        result = self._run_probe_script()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("unstaged12345", result.stdout)

    def test_probe_finds_untracked_new_files(self):
        """Probe should detect concerns matching untracked new files."""
        concern = make_event(
            "concern",
            id="untracked1234",
            content="scripts/new.py missing validation",
            files=["scripts/new.py"],
            severity="medium",
        )
        self._seed_events([concern])

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "new.py").write_text("print('new')\n")

        result = self._run_probe_script()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("untracked1234", result.stdout)


if __name__ == "__main__":
    unittest.main()
