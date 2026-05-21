#!/usr/bin/env python3
"""Tests for the [verify-deferred] debt escape (story-002 / Milestone 5).

When a commit message is prefixed [verify-deferred] <rationale> and the
in-progress story still has untouched verify paths, bash_post_tool records a
`debt` event carrying the rationale and the deferred paths. A plain commit,
or a [verify-deferred] commit that actually touched everything, records none.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
import sprint_store
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_sprint_dict, make_story_dict
from event_helpers import events_of_type


class TestVerifyDeferredDebt(_HookTestCase):
    def _save_in_progress_story(self):
        story = make_story_dict(
            id="story-001",
            status="in-progress",
            acceptance_execution={"type": "pytest", "command": "pytest tests/x.py"},
        )
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _commit(self, body, untouched):
        with (
            patch_commits(
                files=["plugins/xp-agents/scripts/x.py"], body=body, head_sha="def456"
            ),
            patch("branching.get_story_base_branch", return_value="base"),
            patch("verify_paths.untouched_verify_paths", return_value=untouched),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=f"git commit -m '{body}'",
                    stdout="[main def456] msg\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        return events_of_type(self._read_events(), _common.DEBT)

    def test_verify_deferred_records_debt(self):
        self._save_in_progress_story()
        debts = self._commit(
            "[verify-deferred] shipping under deadline", ["tests/x.py"]
        )
        self.assertEqual(len(debts), 1)
        self.assertIn("shipping under deadline", debts[0]["content"])
        self.assertEqual(debts[0]["files"], ["tests/x.py"])

    def test_deferred_rationale_excludes_trailers(self):
        self._save_in_progress_story()
        body = (
            "[verify-deferred] shipping under deadline\n\n"
            "Resolves-Event: abc123\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>"
        )
        debts = self._commit(body, ["tests/x.py"])
        self.assertEqual(len(debts), 1)
        self.assertIn("shipping under deadline", debts[0]["content"])
        self.assertNotIn("Co-Authored-By", debts[0]["content"])
        self.assertNotIn("Resolves-Event", debts[0]["content"])

    def test_plain_commit_records_no_debt(self):
        self._save_in_progress_story()
        debts = self._commit("ordinary work", ["tests/x.py"])
        self.assertEqual(debts, [])

    def test_deferred_but_all_touched_records_no_debt(self):
        self._save_in_progress_story()
        debts = self._commit("[verify-deferred] but I did touch it", [])
        self.assertEqual(debts, [])


if __name__ == "__main__":
    unittest.main()
