#!/usr/bin/env python3
"""E2E tests for quality-review resolves-trailer probe.

Covers resolves_probe.changed_files + find_probe_candidates: surfaces
open concerns whose files intersect changed files so the quality-review
subagent sees them before the commit.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import resolves_probe
from conftest import _IntegrationTestCase, make_event
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS


class TestQualityReviewProbeE2E(_IntegrationTestCase):
    def _run_probe(self) -> list[dict]:
        changed = resolves_probe.changed_files(str(self.tmpdir))
        if not changed:
            return []
        return resolves_probe.find_probe_candidates(
            self.smm_dir, changed, resolves=[], cwd=str(self.tmpdir)
        )

    def test_probe_surfaces_matching_concerns(self):
        concern = make_event(
            EVENT_TYPE_CONCERN,
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

        candidates = self._run_probe()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "abc123def456")

    def test_probe_then_pre_commit_emits_probe_event(self):
        """Quality-review probe + pre-commit both surface same concern."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
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

        candidates = self._run_probe()
        self.assertEqual(len(candidates), 1)

        pre_commit_result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Fix auth'"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        # Block: candidates exist + no trailer. Probe event still writes
        # before the block, so both probe-fires (quality-review + pre-commit)
        # land in events.jsonl.
        self.assertEqual(pre_commit_result.returncode, 2, msg=pre_commit_result.stderr)

        events = self._read_events()
        probes = [
            e
            for e in events
            if e.get("type") == EVENT_TYPE_STATUS
            and e.get("content", "").startswith("resolves_probe_shown:")
        ]
        self.assertEqual(len(probes), 1)

    def test_probe_finds_unstaged_modified_files(self):
        """Probe should detect concerns matching unstaged (not git-added) files."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
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

        candidates = self._run_probe()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "unstaged12345")

    def test_probe_finds_untracked_new_files(self):
        """Probe should detect concerns matching untracked new files."""
        concern = make_event(
            EVENT_TYPE_CONCERN,
            id="untracked1234",
            content="scripts/new.py missing validation",
            files=["scripts/new.py"],
            severity="medium",
        )
        self._seed_events([concern])

        (self.tmpdir / "scripts").mkdir(exist_ok=True)
        (self.tmpdir / "scripts" / "new.py").write_text("print('new')\n")

        candidates = self._run_probe()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], "untracked1234")


if __name__ == "__main__":
    unittest.main()
