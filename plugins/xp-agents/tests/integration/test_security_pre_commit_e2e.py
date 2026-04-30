#!/usr/bin/env python3
"""Story-004 capstone: E2E commit-block integration for Tier 1.

Subprocess-level tests that exercise the full pre_tool_bash.py pipeline
against a real temp git repo: stdin JSON parsing → git diff --cached →
security_scanner.scan_diff → BlockedError → exit 2 + stderr message.

Story-003's unit tests use @patch("commits.get_staged_diff"). These
tests close that gap by running the unmocked path end-to-end.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import security
from conftest import _IntegrationTestCase, _make_bash_input

_AKIA_LINE = 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n'
_CLEAN_LINE = 'def hello():\n    return "hi"\n'
_NOQA_LINE = 'aws_key = "AKIAIOSFODNN7EXAMPLE"  # noqa: secret\n'


class TestSecurityPreCommitE2E(_IntegrationTestCase):
    """Real subprocess + real git repo Tier 1 commit-block verification."""

    def _stage(self, name: str, content: str) -> None:
        (self.tmpdir / name).write_text(content)
        subprocess.run(
            ["git", "add", name],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def _commit_input(self) -> dict:
        return _make_bash_input(command="git commit -m 'wip'", cwd=str(self.tmpdir))

    def test_aws_key_in_staged_file_blocks_commit(self):
        """AC #1: planted AKIA → exit 2, stderr names pattern + file:line."""
        security.write_security_triaged(self.smm_dir)
        self._stage("secrets.py", _AKIA_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("aws-access-key", result.stderr)
        self.assertIn("secrets.py:1", result.stderr)

    def test_clean_staged_file_passes(self):
        """AC #2: clean staged code → exit 0, no Tier 1 message."""
        security.write_security_triaged(self.smm_dir)
        self._stage("app.py", _CLEAN_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Tier 1", result.stderr)

    def test_noqa_secret_suppression_respected(self):
        """AC #3: AKIA + `# noqa: secret` → exit 0 (suppression honored)."""
        security.write_security_triaged(self.smm_dir)
        self._stage("intentional.py", _NOQA_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("aws-access-key", result.stderr)

    def test_full_pipeline_blocks_then_passes_after_fix(self):
        """AC #4: developer workflow — secret blocks, suppression unblocks."""
        security.write_security_triaged(self.smm_dir)

        self._stage("workflow.py", _AKIA_LINE)
        blocked = self._run_script("pre_tool_bash.py", self._commit_input())
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertIn("aws-access-key", blocked.stderr)

        # Developer adds the suppression marker and re-stages.
        self._stage("workflow.py", _NOQA_LINE)
        # Triage marker may have been consumed; re-write before second pass.
        security.write_security_triaged(self.smm_dir)

        unblocked = self._run_script("pre_tool_bash.py", self._commit_input())
        self.assertEqual(unblocked.returncode, 0, unblocked.stderr)
        self.assertNotIn("aws-access-key", unblocked.stderr)

    def test_tier1_fires_before_security_triage_gate(self):
        """AC #4 (gate ordering): planted secret + NO triage marker → still
        blocks with the Tier 1 message, not the triage-required message."""
        # Deliberately do NOT write the security-triaged marker.
        self._stage("ordering.py", _AKIA_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("aws-access-key", result.stderr)
        self.assertNotIn("xp-security-triage", result.stderr)


if __name__ == "__main__":
    unittest.main()
