#!/usr/bin/env python3
"""Tests for scripts/verify_acceptance.py.

The CLI reads a story by ID from sprint.json, runs every command in
its `acceptance_execution` block in order, and exits non-zero on the
first failing command (naming it in stderr). Back-compat: a story
with the legacy `command: str` shape is treated as a one-element list.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import sprint_store
from conftest import _SMMTestCase, make_sprint_dict, make_story_dict, run_cli

_VERIFY_ACCEPTANCE = (
    Path(__file__).parent.parent.parent / "scripts" / "verify_acceptance.py"
)


class TestVerifyAcceptance(_SMMTestCase):
    def _save_sprint_with_story(self, ae: dict, story_id: str = "story-001") -> None:
        story = make_story_dict(id=story_id, acceptance_execution=ae)
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _verify(self, story_id: str):
        return run_cli(_VERIFY_ACCEPTANCE, ["--story", story_id], self.smm_dir)

    def test_all_green_exits_zero(self):
        self._save_sprint_with_story(
            {"type": "bash", "commands": ["true", "true", "true"]}
        )
        result = self._verify("story-001")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_red_exits_nonzero_and_names_command(self):
        self._save_sprint_with_story(
            {"type": "bash", "commands": ["true", "false", "true"]}
        )
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("false", result.stderr)

    def test_stops_at_first_failure(self):
        # The third command writes a sentinel; if the second's failure
        # didn't stop iteration, the file would exist.
        sentinel = self.smm_dir / "should-not-exist.txt"
        self._save_sprint_with_story(
            {
                "type": "bash",
                "commands": ["true", "false", f"touch {sentinel}"],
            }
        )
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            sentinel.exists(),
            "verify_acceptance kept running past the first failure",
        )

    def test_unknown_story_id_exits_nonzero(self):
        self._save_sprint_with_story({"type": "bash", "commands": ["true"]})
        result = self._verify("story-bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected an error message on stderr")

    def test_back_compat_single_command_string(self):
        # Story shape from before sprint-062: `command: str`.
        self._save_sprint_with_story({"type": "bash", "command": "true"})
        result = self._verify("story-001")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_back_compat_single_command_string_failure(self):
        self._save_sprint_with_story({"type": "bash", "command": "false"})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("false", result.stderr)

    def test_multi_command_failure_names_index_and_command(self):
        self._save_sprint_with_story({"type": "bash", "commands": ["true", "false"]})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commands[1]", result.stderr)
        self.assertIn("false", result.stderr)

    def test_single_command_failure_keeps_legacy_format(self):
        # Pinned bit-for-bit: downstream tooling greps for `command failed`.
        self._save_sprint_with_story({"type": "bash", "commands": ["false"]})
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("command failed", result.stderr)
        self.assertNotIn("commands[", result.stderr)

    def test_no_sprint_exits_nonzero(self):
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip(), "expected an error message on stderr")

    def test_story_without_acceptance_execution_exits_nonzero(self):
        story = make_story_dict(id="story-001")
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)
        result = self._verify("story-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_smm_dir_visible_in_subprocess(self):
        # AC commands that reference $SMM_DIR (e.g. to read sprint state, append
        # a marker, etc.) must see it in the child env. The fix is for
        # verify_acceptance to inject it from its --smm-dir arg — relying on
        # the caller to have exported SMM_DIR is the bug (sister concern of
        # feedback_acceptance_command_path_drift).
        #
        # _SMMTestCase pins SMM_DIR in os.environ for test convenience, which
        # masks the production gap (callers like /xp-accept do NOT export it).
        # Strip it here to model the real-world parent env.
        self._save_sprint_with_story(
            {"type": "bash", "commands": ['test -n "$SMM_DIR"']}
        )
        env_no_smm = {k: v for k, v in os.environ.items() if k != "SMM_DIR"}
        with patch.dict(os.environ, env_no_smm, clear=True):
            result = self._verify("story-001")
        self.assertEqual(
            result.returncode,
            0,
            f"$SMM_DIR not propagated to AC subprocess; stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
