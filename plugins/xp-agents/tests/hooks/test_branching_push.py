#!/usr/bin/env python3
"""Create-time push contract for branching.py create_*_branch wrappers.

Asymmetric by design (decision sprint-plan-push-at-create):

- story / free / scaffold creation does NOT push — a freshly-created branch
  holds no commits beyond its base, so pushing only adds a network round-trip
  (and fires the project's pre-push hook) for nothing. These are frequent and
  reach the remote at close time (`close_common.py` push), not at creation.
- sprint / plan creation DOES push (when a remote exists) — they are
  infrequent and the first child merge (story->sprint, sprint->plan) needs a
  remote ref to PR against, plus immediate off-machine backup. The one
  pre-push hook fire per sprint/plan creation is the accepted cost.

The story wrapper pins the no-push half of the shared
`_create_or_resume_branch` path; the sprint/plan wrappers add their own push.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching
from _bases import _AssertNotNoneMixin

_init_repo = _bf.init_repo
_write_system_context = _bf.write_system_context
_add_bare_remote = _bf.add_bare_remote
_remote_has_branch = _bf.remote_has_branch
_checkout_main = _bf.checkout_main


class _BasePushTest(_AssertNotNoneMixin, unittest.TestCase):
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


class TestStoryCreateDoesNotPush(_BasePushTest):
    """Story create never pushes. Pins the no-push contract for the shared
    `_create_or_resume_branch` path that story/free/scaffold route through."""

    def test_fresh_create_does_not_push(self):
        td, smm = self._setup_repo()
        name = branching.create_story_branch(td, "story-001", "demo", smm)
        name = self._assert_not_none(name)
        self.assertFalse(
            _remote_has_branch(td, name),
            "story create pushed the branch to origin — it should reach the "
            "remote at close time, not creation",
        )

    def test_resume_does_not_push(self):
        td, smm = self._setup_repo()
        first = branching.create_story_branch(td, "story-001", "demo", smm)
        first = self._assert_not_none(first)
        _checkout_main(td)
        second = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertEqual(first, second)
        self.assertFalse(_remote_has_branch(td, first))

    def test_create_succeeds_without_remote(self):
        td, smm = self._setup_repo(with_remote=False)
        name = branching.create_story_branch(td, "story-001", "demo", smm)
        self.assertIsNotNone(name)


class TestSprintPlanPushAtCreate(_BasePushTest):
    """Sprint and plan create push to origin when a remote exists (so the
    first child merge has a PR base), and degrade gracefully without one."""

    def test_sprint_create_pushes(self):
        td, smm = self._setup_repo()
        name = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        name = self._assert_not_none(name)
        self.assertTrue(
            _remote_has_branch(td, name),
            "sprint create should push to origin so story closes have a remote PR base",
        )

    def test_plan_create_pushes(self):
        td, smm = self._setup_repo()
        name = branching.create_plan_branch(td, "demo", smm)
        name = self._assert_not_none(name)
        self.assertTrue(
            _remote_has_branch(td, name),
            "plan create should push to origin so sprint closes have a remote PR base",
        )

    def test_sprint_resume_pushes(self):
        td, smm = self._setup_repo()
        first = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        first = self._assert_not_none(first)
        _checkout_main(td)
        second = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        self.assertEqual(first, second)
        self.assertTrue(_remote_has_branch(td, first))

    def test_sprint_create_succeeds_without_remote(self):
        td, smm = self._setup_repo(with_remote=False)
        name = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        self.assertIsNotNone(name)

    def test_plan_create_succeeds_without_remote(self):
        td, smm = self._setup_repo(with_remote=False)
        name = branching.create_plan_branch(td, "demo", smm)
        self.assertIsNotNone(name)


class TestCreatePushSkipsVerify(_BasePushTest):
    """The create-time push must pass `--no-verify`.

    A freshly-created branch holds no commits beyond its base, so a
    project pre-push hook (e.g. an integration test suite) has nothing
    new to gate. Skipping it avoids a pointless multi-second run AND the
    `branching._git` timeout — a slow suite would raise TimeoutExpired
    and crash creation. The bare-remote fixture has no pre-push hook, so
    this pins the contract by asserting the push argv directly.
    """

    def _capture_push_argv(self, call) -> list[list[str]]:
        pushes: list[list[str]] = []
        real_git = branching._git

        def _spy(args, cwd):
            if len(args) > 1 and args[1] == "push":
                pushes.append(list(args))
            return real_git(args, cwd)

        orig = branching._git
        branching._git = _spy
        try:
            call()
        finally:
            branching._git = orig
        return pushes

    def test_sprint_create_push_uses_no_verify(self):
        td, smm = self._setup_repo()
        pushes = self._capture_push_argv(
            lambda: branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        )
        self.assertTrue(pushes, "sprint create did not push")
        self.assertIn("--no-verify", pushes[0])

    def test_plan_create_push_uses_no_verify(self):
        td, smm = self._setup_repo()
        pushes = self._capture_push_argv(
            lambda: branching.create_plan_branch(td, "demo", smm)
        )
        self.assertTrue(pushes, "plan create did not push")
        self.assertIn("--no-verify", pushes[0])

    def test_create_survives_push_timeout(self):
        """A slow/hung real-remote push (network latency, not the hook)
        raises subprocess.TimeoutExpired from _git — create must catch it
        and still return the branch name, never crash (the branch already
        exists locally and reaches origin at close time as a fallback)."""
        import subprocess as _sp

        td, smm = self._setup_repo()
        real_git = branching._git

        def _git_timeout(args, cwd):
            if len(args) > 1 and args[1] == "push":
                raise _sp.TimeoutExpired(cmd=args, timeout=10)
            return real_git(args, cwd)

        orig = branching._git
        branching._git = _git_timeout
        try:
            name = branching.create_sprint_branch(td, "sprint-001", "demo", smm)
        finally:
            branching._git = orig
        self.assertIsNotNone(name, "create crashed on a push timeout")


if __name__ == "__main__":
    unittest.main()
