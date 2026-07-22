#!/usr/bin/env python3
"""Tests for the delete/merge-branch target resolution in branching_cli_target.

Two halves of one question — "which branch does --branch belong to?": the
membership gate that routes a CURRENT-sprint story branch at its sprint base
(concern 9df23ed3ec84), and what BOTH subcommands do when the sprint.json that
gate reads is unreadable. End-to-end target routing lives in
tests/integration/test_branching_delete.py and test_branching_lifecycle_cli.py.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching_cli
import sprint_store

_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
_seed_sprint_with_stories = _bf.seed_sprint_with_stories


class TestCurrentSprintStoryBranchDetection(unittest.TestCase):
    """The membership gate that decides whether `delete`/`merge-branch` resolve
    the STORY BASE or keep `get_merge_target` (concern 9df23ed3ec84).

    Detection, not resolution: which recorded name does this branch actually
    correspond to. These are the arms a subprocess reaches only awkwardly.
    """

    def _seed(self, smm_dir: Path, story_branch: str) -> None:
        _seed_sprint_with_stories(
            smm_dir,
            [("story-001", "done")],
            base_branch="paul/sprint-001-open",
            story_branches={"story-001": story_branch},
        )

    def test_true_for_the_recorded_branch_of_a_story_in_this_sprint(self):
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._seed(smm_dir, "paul/story-001-work")
            self.assertTrue(
                branching_cli._is_current_sprint_story_branch(
                    smm_dir, "paul/story-001-work"
                )
            )

    def test_false_for_a_same_id_branch_this_sprint_did_not_record(self):
        """Story ids restart at story-001 every sprint, so a prior sprint's
        orphan shares an id with a live story routinely. Matching on the id
        alone would claim it — and route its delete at THIS sprint's base."""
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._seed(smm_dir, "paul/story-001-current")
            self.assertFalse(
                branching_cli._is_current_sprint_story_branch(
                    smm_dir, "paul/story-001-prior"
                )
            )

    def test_false_when_there_is_no_sprint(self):
        with tempfile.TemporaryDirectory() as smm:
            self.assertFalse(
                branching_cli._is_current_sprint_story_branch(
                    Path(smm), "paul/story-001-work"
                )
            )

    def test_non_story_branch_never_reads_the_sprint(self):
        """The cheap first gate, proven by a sprint that would RAISE if read:
        free and plan branches must resolve exactly as they did before this
        gate existed, corrupt SMM or not."""
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            (smm_dir / "sprint.json").write_text("{ not json")
            for branch in ("paul/free-tidy", "paul/plan-rework", "main"):
                with self.subTest(branch=branch):
                    self.assertFalse(
                        branching_cli._is_current_sprint_story_branch(smm_dir, branch)
                    )

    def test_corrupt_sprint_raises_rather_than_answering_no(self):
        """Fail closed. Swallowing the corruption would answer "not a story
        branch" and silently prove the delete against primary instead."""
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            (smm_dir / "sprint.json").write_text("{ not json")
            with self.assertRaises(sprint_store.SprintCorruptError):
                branching_cli._is_current_sprint_story_branch(
                    smm_dir, "paul/story-001-work"
                )


class TestCorruptSprintRefusesReadably(unittest.TestCase):
    """Failing closed is right; failing closed with a TRACEBACK is not.

    Reading the sprint at all is new to `delete` and `merge-branch`, so a
    corrupt sprint.json is a new way for both to fail — and both are invoked
    from SKILL prose the user is following. This CLI's rule is that a refusal
    prints the sentence the user has to act on (`create`, `create-free`,
    `get-base --required` all do it); these two must not be the exception.
    """

    _BRANCH = "paul/story-001-work"

    def _run(self, smm: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, _SCRIPT, "--smm-dir", smm, *args],
            capture_output=True,
            text=True,
            env=_bf.GIT_ENV,
        )

    def _corrupt_repo(self, td: str, smm: str) -> None:
        _bf.init_repo(td)
        _bf.make_branch(td, self._BRANCH)
        (Path(smm) / "sprint.json").write_text("{ not json")

    def _assert_readable_refusal(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("sprint.json", result.stderr)

    def test_delete_reports_the_corruption_instead_of_tracebacking(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            self._corrupt_repo(td, smm)
            result = self._run(smm, *["delete", "--cwd", td], "--branch", self._BRANCH)
            self._assert_readable_refusal(result)
            self.assertTrue(
                _bf.branch_exists(td, self._BRANCH),
                "refusing means nothing was deleted",
            )

    def test_merge_branch_reports_the_corruption_instead_of_tracebacking(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            self._corrupt_repo(td, smm)
            result = self._run(
                smm, *["merge-branch", "--cwd", td], "--branch", self._BRANCH
            )
            self._assert_readable_refusal(result)


if __name__ == "__main__":
    unittest.main()
