#!/usr/bin/env python3
"""close_common.py merge prunes the remote source branch after merge.

cmd_merge already deletes the LOCAL source branch and pushes the target;
this pins the matching remote-source cleanup so closed branches don't
accumulate on origin forever. Best-effort: a source with no remote ref
(never pushed) must not abort the merge chain.
"""

import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _branching_fixtures as _bf

_SOURCE = "paul/story-007-demo"
_TARGET = "main"


class TestMergeRemoteSourceCleanup(unittest.TestCase):
    def _setup(self, *, with_remote: bool, push_source: bool) -> str:
        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _bf.init_repo(td)
        if with_remote:
            _bf.add_bare_remote(td)
        # A clean, cleanly-mergeable source branch with one commit.
        _bf.make_commit(td, _SOURCE, "feature.txt", "x", "feat")
        if with_remote and push_source:
            import subprocess

            subprocess.run(
                ["git", "push", "-u", "origin", _SOURCE],
                cwd=td,
                capture_output=True,
                check=True,
                env=_bf.GIT_ENV,
            )
        _bf.checkout_main(td)
        return td

    def test_merge_deletes_remote_source(self):
        td = self._setup(with_remote=True, push_source=True)
        self.assertTrue(_bf.remote_has_branch(td, _SOURCE))  # precondition
        r = _bf.merge_teammate_branch(td, _SOURCE, _TARGET, env=_bf.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(
            _bf.remote_has_branch(td, _SOURCE),
            "merge should prune the remote source branch",
        )
        self.assertFalse(_bf.branch_exists(td, _SOURCE), "local source deleted")
        self.assertTrue(_bf.remote_has_branch(td, _TARGET), "target pushed")

    def test_merge_nonfatal_when_source_not_on_remote(self):
        """Source never pushed → remote --delete fails harmlessly; the
        merge chain still succeeds (rc 0) and the local source is deleted."""
        td = self._setup(with_remote=True, push_source=False)
        self.assertFalse(_bf.remote_has_branch(td, _SOURCE))  # precondition
        r = _bf.merge_teammate_branch(td, _SOURCE, _TARGET, env=_bf.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(_bf.branch_exists(td, _SOURCE))

    def test_merge_without_remote_unchanged(self):
        td = self._setup(with_remote=False, push_source=False)
        r = _bf.merge_teammate_branch(td, _SOURCE, _TARGET, env=_bf.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(_bf.branch_exists(td, _SOURCE))


class TestRemoteDeleteSkipsVerify(unittest.TestCase):
    """The remote-source `--delete` push must pass `--no-verify`.

    A pure ref deletion has nothing to gate, and the target push already
    fired any project pre-push hook — re-running it (e.g. a multi-second
    integration suite) on a delete is pure waste. The bare-remote fixture
    has no pre-push hook, so this pins the contract by spying on the push
    argv in-process.
    """

    def test_remote_delete_push_uses_no_verify(self):
        import close_common

        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _bf.init_repo(td)
        _bf.add_bare_remote(td)
        _bf.make_commit(td, _SOURCE, "feature.txt", "x", "feat")
        subprocess.run(
            ["git", "push", "-u", "origin", _SOURCE],
            cwd=td,
            capture_output=True,
            check=True,
            env=_bf.GIT_ENV,
        )
        _bf.checkout_main(td)

        delete_pushes: list[list[str]] = []
        real_run = subprocess.run

        def _spy(argv, *a, **kw):
            if isinstance(argv, list) and "push" in argv and "--delete" in argv:
                delete_pushes.append(list(argv))
            return real_run(argv, *a, **kw)

        args = argparse.Namespace(
            source=_SOURCE,
            target=_TARGET,
            cwd=td,
            verify_gate=None,
            smm_dir=None,
        )
        orig = close_common.subprocess.run
        close_common.subprocess.run = _spy
        try:
            rc = close_common.cmd_merge(args)
        finally:
            close_common.subprocess.run = orig

        self.assertEqual(rc, 0)
        self.assertTrue(delete_pushes, "remote source was not pruned")
        self.assertIn("--no-verify", delete_pushes[0])


if __name__ == "__main__":
    unittest.main()
