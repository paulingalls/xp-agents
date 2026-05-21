#!/usr/bin/env python3
"""Tests for pre_tool_bash.py verify-touch nudge (story-002 / Milestone 5).

The nudge fires at commit time on a story branch whose in-progress story
declares acceptance-test paths that no commit on base..HEAD has touched. It
is advisory (never blocks) and is suppressed by a [verify-deferred] commit.
The git-walk itself is covered in test_verify_paths.py; here we test the
wiring, mocking the git-backed boundaries.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_bash
import sprint_store
from conftest import _HookTestCase, _make_bash_input, make_sprint_dict, make_story_dict

_STORY_BRANCH = "paul/story-001-feature"
_PYTEST_AE = {"type": "pytest", "command": "pytest tests/x.py"}
_COMMIT_CMD = "git commit -m 'wip'"


class TestVerifyTouchNudge(_HookTestCase):
    def _save_story(self, *, ae=_PYTEST_AE, acs=None):
        story = make_story_dict(id="story-001", status="in-progress")
        story["acceptance_criteria"] = acs if acs is not None else ["a manual AC"]
        if ae is not None:
            story["acceptance_execution"] = ae
        else:
            story.pop("acceptance_execution", None)
        sprint = make_sprint_dict(stories=[story])
        sprint_store.save_sprint(self.smm_dir, sprint, enforce_budget=False)

    def _run(self, *, command=_COMMIT_CMD, branch=_STORY_BRANCH, untouched=None):
        with (
            patch("branching.get_branching_stage", return_value=2),
            patch("branching.is_sprint_branch", return_value=False),
            patch("git_commits.is_git_commit", return_value=True),
            patch("commits.get_code_files_for_review", return_value=[]),
            patch("identity.get_current_branch", return_value=branch),
            patch("branching.get_story_base_branch", return_value="base"),
            patch(
                "verify_paths.untouched_verify_paths",
                return_value=untouched if untouched is not None else [],
            ),
        ):
            return pre_tool_bash.run(
                _make_bash_input(command=command), smm_dir=self.smm_dir
            )

    def test_nudge_fires_naming_untouched_path(self):
        self._save_story()
        result = self._run(untouched=["tests/x.py"])
        result = self._assert_not_none(result)
        self.assertIn("tests/x.py", result)
        self.assertIn("verify", result.lower())

    def test_verify_deferred_suppresses_nudge(self):
        self._save_story()
        result = self._run(
            command="git commit -m '[verify-deferred] shipping under deadline'",
            untouched=["tests/x.py"],
        )
        self.assertNotIn("tests/x.py", result or "")

    def test_all_touched_no_nudge(self):
        self._save_story()
        result = self._run(untouched=[])
        self.assertIsNone(result)

    def test_non_story_branch_no_nudge(self):
        self._save_story()
        result = self._run(branch="paul/random-branch", untouched=["tests/x.py"])
        self.assertIsNone(result)

    def test_no_verify_paths_no_nudge(self):
        self._save_story(ae=None, acs=["only a manual string AC"])
        result = self._run(untouched=["tests/x.py"])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
