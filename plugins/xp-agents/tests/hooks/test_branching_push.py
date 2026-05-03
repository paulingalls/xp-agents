#!/usr/bin/env python3
"""Push-at-create-time tests for every branching.py create_*_branch wrapper.

Pins the contract that each public wrapper (story / sprint / scaffold /
free / plan) pushes its freshly-created branch to origin. A regression
that bypasses _create_or_resume_branch for one wrapper still trips here.

Resume path is explicitly NOT pushed — push -u is only safe when local
matches/leads remote, and a resumed branch may have diverged remotely.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching

_init_repo = _bf.init_repo
_write_system_context = _bf.write_system_context
_seed_plan = _bf.seed_plan
_add_bare_remote = _bf.add_bare_remote
_remote_has_branch = _bf.remote_has_branch
_checkout_main = _bf.checkout_main


class _BasePushTest(unittest.TestCase):
    """Sets up a primed repo: stage 2, primary `main`, optional remote."""

    stage = 2

    def _setup_repo(self, with_remote: bool = True) -> tuple[str, Path]:
        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _init_repo(td)
        smm = Path(td) / "smm"
        smm.mkdir()
        _write_system_context(smm, self.stage)
        # Exclude smm/ and the bare-remote dir from worktree-clean checks
        # so create_*_branch's dirty-tree guard doesn't reject these tests.
        (Path(td) / ".git" / "info" / "exclude").write_text("smm/\nremote.git/\n")
        if with_remote:
            _add_bare_remote(td)
        return td, smm


class TestStoryBranchPushes(_BasePushTest):
    """Story-wrapper holds the full path matrix (silent, resume, failure)
    because all 5 wrappers share `_create_or_resume_branch`. Sister
    classes (Sprint/Scaffold/Free/Plan) only smoke-test the wire-up.
    Don't copy the matrix into them — same code path, same coverage."""

    def test_pushes_freshly_created(self):
        td, smm = self._setup_repo()
        name = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertIsNotNone(name)
        self.assertTrue(_remote_has_branch(td, name))

    def test_silent_when_no_remote(self):
        td, smm = self._setup_repo(with_remote=False)
        name = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertIsNotNone(name)

    def test_does_not_push_on_resume(self):
        td, smm = self._setup_repo()
        first = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertTrue(_remote_has_branch(td, first))
        _checkout_main(td)
        # Patch at source — branching.py calls via `git_remote.push_branch`
        # (module-attribute access). A future `from git_remote import push_branch`
        # refactor would silently skip this mock.
        with patch("git_remote.push_branch") as mock_push:
            second = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertEqual(first, second)
        mock_push.assert_not_called()

    def test_push_failure_does_not_abort_create(self):
        td, smm = self._setup_repo()
        with patch("git_remote.push_branch", return_value=False):
            name = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertIsNotNone(name)


class TestSprintBranchPushes(_BasePushTest):
    def test_pushes_freshly_created(self):
        td, smm = self._setup_repo()
        _seed_plan(smm)
        name = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        self.assertIsNotNone(name)
        self.assertTrue(_remote_has_branch(td, name))

    def test_does_not_push_on_resume(self):
        td, smm = self._setup_repo()
        _seed_plan(smm)
        first = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        _checkout_main(td)
        with patch("git_remote.push_branch") as mock_push:
            second = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        self.assertEqual(first, second)
        mock_push.assert_not_called()


class TestScaffoldBranchPushes(_BasePushTest):
    stage = 1

    def test_pushes_freshly_created(self):
        td, smm = self._setup_repo()
        name = branching.create_scaffold_branch(td, "cli", smm)
        self.assertIsNotNone(name)
        self.assertTrue(_remote_has_branch(td, name))

    def test_does_not_push_on_resume(self):
        td, smm = self._setup_repo()
        first = branching.create_scaffold_branch(td, "cli", smm)
        _checkout_main(td)
        with patch("git_remote.push_branch") as mock_push:
            second = branching.create_scaffold_branch(td, "cli", smm)
        self.assertEqual(first, second)
        mock_push.assert_not_called()


class TestFreeBranchPushes(_BasePushTest):
    stage = 1

    def test_pushes_freshly_created(self):
        td, smm = self._setup_repo()
        name = branching.create_free_branch(td, "demo", smm)
        self.assertIsNotNone(name)
        self.assertTrue(_remote_has_branch(td, name))

    def test_does_not_push_on_resume(self):
        td, smm = self._setup_repo()
        first = branching.create_free_branch(td, "demo", smm)
        _checkout_main(td)
        with patch("git_remote.push_branch") as mock_push:
            second = branching.create_free_branch(td, "demo", smm)
        self.assertEqual(first, second)
        mock_push.assert_not_called()


class TestPlanBranchPushes(_BasePushTest):
    def test_pushes_freshly_created(self):
        td, smm = self._setup_repo()
        name = branching.create_plan_branch(td, "demo", smm)
        self.assertIsNotNone(name)
        self.assertTrue(_remote_has_branch(td, name))

    def test_does_not_push_on_resume(self):
        td, smm = self._setup_repo()
        first = branching.create_plan_branch(td, "demo", smm)
        _checkout_main(td)
        with patch("git_remote.push_branch") as mock_push:
            second = branching.create_plan_branch(td, "demo", smm)
        self.assertEqual(first, second)
        mock_push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
