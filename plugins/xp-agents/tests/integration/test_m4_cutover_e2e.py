#!/usr/bin/env python3
"""Story-004 capstone: M-4 cutover end-to-end acceptance.

Renders the milestone done-state into executable assertions:
- Commits clear with `/simplify` + `/xp-quality-review` only.
- Tier 1 deterministic patterns still block on staged secrets.
- Doc set carries zero `security_review_done` references.
- `markers._REVIEW_FLAGS` and `_DEFAULT_REVIEW_CYCLE` no longer
  contain `security_review_done`.
- Below-threshold commits no longer auto-write the security marker
  (absorbs story-001 close-reviewer concern 26d40317ed82 — the
  deleted exemption fallback).
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
import security
from conftest import _PLUGIN_ROOT, _IntegrationTestCase, _make_bash_input

_REPO_ROOT = _PLUGIN_ROOT.parent.parent

_CLEAN_LINE = 'def hello():\n    return "hi"\n'
_AKIA_LINE = 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n'

# Spread the post-M-4 default so the schema stays in lockstep with markers.py;
# we only flip the two surviving flags.
_REVIEW_DONE = dict(markers._DEFAULT_REVIEW_CYCLE) | {
    "simplify_done": True,
    "quality_review_done": True,
}


class TestM4CutoverE2E(_IntegrationTestCase):
    """Integration-level confirmation of the M-4 cutover done-state."""

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

    def test_commit_with_only_simplify_and_quality_passes(self):
        markers.write_review_cycle(self.smm_dir, "main", _REVIEW_DONE)
        self._stage("app.py", _CLEAN_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("xp-security-triage", result.stderr)
        self.assertNotIn("security-review", result.stderr)

    def test_tier1_pattern_still_blocks_after_m4(self):
        markers.write_review_cycle(self.smm_dir, "main", _REVIEW_DONE)
        self._stage("secrets.py", _AKIA_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("aws-access-key", result.stderr)

    def test_below_threshold_no_marker_auto_written(self):
        """Absorbs close-reviewer concern 26d40317ed82: the deleted
        exemption fallback no longer auto-writes a security marker."""
        self._stage("solo.py", _CLEAN_LINE)

        result = self._run_script("pre_tool_bash.py", self._commit_input())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(security.security_triaged_exists(self.smm_dir, "main"))

    def test_review_flags_no_longer_contain_security(self):
        self.assertNotIn("security_review_done", markers._REVIEW_FLAGS)
        self.assertNotIn("security_review_done", markers._DEFAULT_REVIEW_CYCLE)

    def test_doc_grep_zero_security_review_done_references(self):
        files = [
            _PLUGIN_ROOT / "PROCESS_GUIDE.md",
            _REPO_ROOT / "CLAUDE.md",
            _REPO_ROOT / "docs" / "ARCHITECTURE.md",
            _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md",
        ]
        # Fail loud if a doc moves — silent skip would let a rename hide
        # surviving references to the retired flag.
        for f in files:
            self.assertTrue(f.exists(), f"M-4 doc-grep target missing: {f}")
        offenders = []
        for f in files:
            for i, line in enumerate(f.read_text().splitlines(), start=1):
                if "security_review_done" in line:
                    offenders.append(f"{f}:{i}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "M-4 doc set must not reference security_review_done; found:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
