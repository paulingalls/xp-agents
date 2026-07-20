#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — apply-commit subcommand (stage 0 + stage 2).

Split out of test_scaffold_cli_apply.py (which grew past the 500-line
cap). Covers apply-commit's stage-0 happy path (sha + branch, concern-id
trailer) and the stage-2 protected-base behavior (forks a child branch
off main, refuses on a story branch). The shared _ApplyCliTestBase
fixture lives in `_scaffold_cli_apply_helpers.py`; this file adds
`_ApplyCliCommitTestBase`, which layers a real git repo + stage config
on top of it for these tests only.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _helpers import init_git_identity, run_git
from _scaffold_cli_apply_helpers import _ApplyCliTestBase
from conftest import run_cli

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


class _ApplyCliCommitTestBase(_ApplyCliTestBase):
    """_ApplyCliTestBase + git init + identity + initial commit + stage config.

    Sets up a real git tempdir so apply-commit can actually run git.
    Subclasses override the ``stage`` class attribute for Stage 1+ tests.
    """

    stage: int = 0

    def setUp(self) -> None:
        super().setUp()
        init_git_identity(self._repo)
        run_git(["git", "add", "package.json"], self._repo)
        run_git(["git", "commit", "-m", "[chore] seed"], self._repo)
        (self.smm_dir / "system_context.json").write_text(
            json.dumps({"branching_strategy": {"stage": self.stage}}),
            encoding="utf-8",
        )


class TestApplyCommitStageZero(_ApplyCliCommitTestBase):
    def test_happy_path_returns_ok_with_sha_and_branch(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["sha"])
        self.assertEqual(payload["branch"], "main")

    def test_concern_id_in_resolves_event_trailer(self) -> None:
        write_payload = self._apply_write(self._plan())
        run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
                "--concern-id",
                "abc123def456",
            ],
            self.smm_dir,
        )
        body = run_git(["git", "log", "-1", "--format=%B"], self._repo).stdout
        self.assertIn("Resolves-Event: abc123def456", body)


class TestApplyCommitStageTwoOnProtectedBase(_ApplyCliCommitTestBase):
    stage = 2

    def test_forks_child_off_main_at_stage_2(self) -> None:
        """On main (protected) at stage 2, apply-commit forks the scaffold
        child off main and commits there instead of refusing — branching off
        a protected base is fine; the child keeps the commit off main."""
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload.get("reason"))
        self.assertTrue(payload["branch"].endswith("/scaffold"))

    def test_refuses_on_story_branch_at_stage_2(self) -> None:
        """apply-commit on a story branch surfaces commit_scaffold's refusal
        as an ok=False payload with guidance to the sprint branch."""
        run_git(["git", "checkout", "-b", "paulingalls/story-007-x"], self._repo)
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        reason = payload["reason"].lower()
        self.assertIn("story", reason)
        self.assertIn("sprint", reason)


if __name__ == "__main__":
    unittest.main()
