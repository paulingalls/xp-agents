#!/usr/bin/env python3
"""Create-time no-push contract for branching.py create_*_branch wrappers.

Branch creation does NOT push to origin — a freshly-created branch holds
no commits beyond its base, so pushing it only adds a network round-trip
(and fires the project's pre-push hook) for nothing. Branches reach the
remote at close time (`close_common.py` push), not at creation.

All five wrappers (story / sprint / scaffold / free / plan) share
`_create_or_resume_branch`, so the story wrapper pins the contract for the
shared path; this is the regression guard against re-introducing a
create-time push.
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


class TestCreateDoesNotPush(_BasePushTest):
    """Create never pushes. Story wrapper pins the shared
    `_create_or_resume_branch` path; the other wrappers route through it."""

    def test_fresh_create_does_not_push(self):
        td, smm = self._setup_repo()
        name = branching.create_story_branch(td, "story-001", "demo", smm)
        name = self._assert_not_none(name)
        self.assertFalse(
            _remote_has_branch(td, name),
            "create pushed the branch to origin — it should reach the remote "
            "at close time, not creation",
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


if __name__ == "__main__":
    unittest.main()
