#!/usr/bin/env python3
"""Tests for branching.py — Stage 1->2 auto-promotion and worktree detection.

Covers: get_branching_stage auto-promote side effect, is_git_worktree.

Split from test_branching.py — pure branch-name/stage helpers remain there;
protected/primary/merge-target resolution is in test_branching_protection.py.
Commit message parsing tests (extract_commit_message,
is_escape_hatch_commit) are in test_commits.py.

Git-operation lifecycle tests (create, merge, delete, CLI) are in
test_branching_lifecycle.py.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import branching
from _system_context_fixtures import valid_doc
from conftest import _SMMTestCase
from event_schema import EVENT_TYPE_DECISION


class TestAutoPromote(_SMMTestCase):
    """Stage 1 -> Stage 2 auto-promotion (M-7 plugin floor)."""

    def _write_ctx(self, stage: int) -> None:
        doc = valid_doc(branching_strategy={"stage": stage})
        (self.smm_dir / "system_context.json").write_text(json.dumps(doc))

    def _stage_in_file(self) -> int:
        ctx = json.loads((self.smm_dir / "system_context.json").read_text())
        return ctx["branching_strategy"]["stage"]

    def _promote_events(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("topic") == "branching-stage-auto-promote"
        ]

    def test_promotes_stage_1_to_2_in_file(self):
        self._write_ctx(1)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(self._stage_in_file(), 2)

    def test_emits_one_decision_event(self):
        self._write_ctx(1)
        branching.get_branching_stage(self.smm_dir)
        events = self._promote_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], EVENT_TYPE_DECISION)
        self.assertEqual(events[0]["agent_id"], "branching")

    def test_idempotent_no_duplicate_event(self):
        self._write_ctx(1)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(len(self._promote_events()), 1)

    def test_stage_0_unchanged(self):
        self._write_ctx(0)
        before = (self.smm_dir / "system_context.json").read_text()
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 0)
        self.assertEqual((self.smm_dir / "system_context.json").read_text(), before)
        self.assertEqual(self._promote_events(), [])

    def test_stage_2_unchanged(self):
        self._write_ctx(2)
        before = (self.smm_dir / "system_context.json").read_text()
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual((self.smm_dir / "system_context.json").read_text(), before)
        self.assertEqual(self._promote_events(), [])

    def test_missing_system_context_returns_zero(self):
        self.assertFalse((self.smm_dir / "system_context.json").exists())
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 0)
        self.assertEqual(self._promote_events(), [])

    def test_create_sprint_branch_promotes_stage_1_e2e(self):
        """E2E AC for story-001: a Stage 1 fixture, when create_sprint_branch
        runs (which reads stage internally via get_branching_stage), the
        sprint branch IS created (the stage>=2 floor gate passes because
        auto-promote ran transparently) AND the persisted file now reads
        stage=2 for subsequent reads.

        Mocks the git subprocess + identity + push surfaces so the test
        exercises the composition (_create_or_resume_branch -> stage gate
        -> get_branching_stage -> auto-promote) without a real git repo.
        """
        self._write_ctx(1)

        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("branching.identity.user_namespace", return_value="paul"),
            # branch_exists/is_worktree_clean/_git are read inside
            # _create_or_resume_branch, which lives in branching_core.py
            # (extracted to keep branching.py under the file-size cap) — patch
            # where that caller lives, per this module's "patch where the
            # caller lives" convention.
            patch("branching_core.branch_exists", return_value=False),
            patch("branching_core.is_worktree_clean", return_value=True),
            patch("branching_core._git", return_value=fake_proc),
        ):
            result = branching.create_sprint_branch(
                cwd=str(self.smm_dir),
                sprint_id="sprint-001",
                slug="e2e",
                smm_dir=self.smm_dir,
            )
        self.assertEqual(result, "paul/sprint-001-e2e")
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(len(self._promote_events()), 1)

    def test_create_story_branch_promotes_stage_1_e2e(self):
        """E2E AC for story-001: a Stage 1 fixture, when create_story_branch
        runs (which reads stage internally via get_branching_stage through
        _create_or_resume_branch), the story branch IS created (the
        stage>=2 floor gate passes because auto-promote ran transparently)
        AND the persisted file now reads stage=2.

        Mirrors test_create_sprint_branch_promotes_stage_1_e2e but for the
        story-branch path. Pins the contract that the auto-promote
        chokepoint fires on every stage-aware branch-create entry, not
        just the sprint path.
        """
        self._write_ctx(1)

        fake_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("branching.identity.user_namespace", return_value="paul"),
            # branch_exists/is_worktree_clean/_git are read inside
            # _create_or_resume_branch, which lives in branching_core.py
            # (extracted to keep branching.py under the file-size cap) — patch
            # where that caller lives, per this module's "patch where the
            # caller lives" convention.
            patch("branching_core.branch_exists", return_value=False),
            patch("branching_core.is_worktree_clean", return_value=True),
            patch("branching_core._git", return_value=fake_proc),
            # create_story_branch now VERIFIES the base it is handed against git
            # (trusted_story_base -> ref_exists). cwd here is the SMM temp dir,
            # not a repo, and that check crosses into branch_resolution — where
            # `patch("branching._git")` does not reach — so fake the collaborator
            # in the module that owns the caller, like branch_exists above.
            patch("branching.trusted_story_base", return_value="main"),
            # short-circuits the post-create set_story_branch lookup
            patch("branching.sprint_store.sprint_exists", return_value=False),
        ):
            result = branching.create_story_branch(
                cwd=str(self.smm_dir),
                story_id="story-001",
                slug="e2e",
                smm_dir=self.smm_dir,
                base="main",
            )
        self.assertEqual(result, "paul/story-001-e2e")
        self.assertEqual(self._stage_in_file(), 2)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)
        self.assertEqual(len(self._promote_events()), 1)


class TestIsGitWorktree(unittest.TestCase):
    """is_git_worktree distinguishes a checkable working tree from a path that
    can't be status-checked at all (missing dir / not a repo), so callers don't
    conflate an errored `git status` with a dirty tree."""

    def test_real_repo_is_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init"], cwd=td, capture_output=True, check=True)
            self.assertTrue(branching.is_git_worktree(td))

    def test_non_repo_dir_is_not_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(branching.is_git_worktree(td))

    def test_missing_path_is_not_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            missing = str(Path(td) / "does-not-exist")
            # A missing cwd makes subprocess raise, not return non-zero — the
            # helper must swallow that and report "not a worktree", never crash.
            self.assertFalse(branching.is_git_worktree(missing))

    def test_hung_git_timeout_is_not_worktree(self):
        # _git runs with a timeout, so a hung `git rev-parse` raises
        # TimeoutExpired (a SubprocessError, not OSError). The helper must
        # swallow it and report "not a worktree" rather than crash the merge.
        with patch.object(
            branching,
            "_git",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            self.assertFalse(branching.is_git_worktree("/any/path"))


if __name__ == "__main__":
    unittest.main()
