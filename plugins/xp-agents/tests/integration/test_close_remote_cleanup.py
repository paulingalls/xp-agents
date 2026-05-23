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


class TestMergeEmitsCommitEvent(unittest.TestCase):
    """cmd_merge appends a type=commit event after branching.merge_branch
    returns. The Bash PreToolUse commit hook only sees top-level `git commit`
    shells — the inner `git merge --no-ff` subprocess is invisible to it.
    Emitting from cmd_merge closes the merge-gap commit-event hole.
    """

    def _make_smm(self) -> Path:
        smm_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(smm_ctx.cleanup)
        smm_dir = Path(smm_ctx.name)
        (smm_dir / "events.lock").touch()
        (smm_dir / "events.jsonl").touch()
        # _SOURCE = "paul/story-007-demo" → extract_story_id → "story-007".
        # Seed the sprint with that story so sprint_store.load_sprint
        # returns a non-None dict — gives metadata.sprint_id its value.
        _bf.seed_sprint_with_stories(smm_dir, [("story-007", "in-progress")])
        return smm_dir

    def _make_repo(self, code_file: str = "feature.py") -> str:
        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _bf.init_repo(td)
        _bf.make_commit(td, _SOURCE, code_file, "x", "feat")
        _bf.checkout_main(td)
        return td

    def _make_args(
        self, td: str, smm_dir: Path | None, *, source: str = _SOURCE
    ) -> argparse.Namespace:
        return argparse.Namespace(
            source=source,
            target=_TARGET,
            cwd=td,
            verify_gate=None,
            smm_dir=str(smm_dir) if smm_dir else None,
            force_verify=False,
        )

    def _read_commit_events(self, smm_dir: Path) -> list[dict]:
        import _common

        events, _ = _common.load_events_with_resolutions(smm_dir)
        return [e for e in events if e.get("type") == _common.COMMIT]

    def _head_sha(self, td: str) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=td,
            capture_output=True,
            text=True,
            check=True,
            env=_bf.GIT_ENV,
        )
        return r.stdout.strip()

    def test_merge_emits_commit_event(self):
        import close_common

        td = self._make_repo("feature.py")
        smm_dir = self._make_smm()
        rc = close_common.cmd_merge(self._make_args(td, smm_dir))
        self.assertEqual(rc, 0)

        commit_events = self._read_commit_events(smm_dir)
        self.assertEqual(len(commit_events), 1, commit_events)
        ev = commit_events[0]
        meta = ev["metadata"]
        self.assertEqual(meta["commit_hash"], self._head_sha(td))
        self.assertTrue(meta["code_commit"])
        self.assertEqual(meta["code_file_count"], 1)
        self.assertIn("feature.py", ev["files"])
        self.assertEqual(meta["sprint_id"], "sprint-001")  # from seed fixture
        self.assertEqual(meta["story_id"], "story-007")  # from _SOURCE shape
        # is_merge flag excludes this event from resolves_link_rate accounting
        # (merge commits aggregate story commits that carry their own trailers).
        self.assertTrue(meta["is_merge"])

    def test_merge_with_sprint_source_not_tagged_free_session(self):
        """The default _SOURCE is a story-shaped branch, not a free branch.
        The merge event MUST NOT carry metadata.is_free_session — that flag
        is reserved for free-mode merges so retro_metrics can bucket them."""
        import close_common

        td = self._make_repo("feature.py")
        smm_dir = self._make_smm()
        rc = close_common.cmd_merge(self._make_args(td, smm_dir))
        self.assertEqual(rc, 0)
        meta = self._read_commit_events(smm_dir)[0]["metadata"]
        self.assertNotIn("is_free_session", meta)

    def test_merge_with_free_source_tagged_is_free_session(self):
        """A free→target merge tags the commit event is_free_session=True
        (alongside is_merge). Retro_metrics' conditional-include filter
        treats it like any other merge for the standard rate, but the flag
        is preserved for future free-mode bucket metrics."""
        import close_common

        free_source = "paulingalls/free-2026-05-23-explore-foo"
        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _bf.init_repo(td)
        _bf.make_commit(td, free_source, "feature.py", "x", "feat")
        _bf.checkout_main(td)
        smm_dir = self._make_smm()
        rc = close_common.cmd_merge(self._make_args(td, smm_dir, source=free_source))
        self.assertEqual(rc, 0)
        meta = self._read_commit_events(smm_dir)[0]["metadata"]
        self.assertTrue(meta["is_merge"])
        self.assertTrue(meta["is_free_session"])
        # extract_story_id on a free branch returns None — no story_id key.
        self.assertNotIn("story_id", meta)

    def test_merge_does_not_emit_when_smm_dir_absent(self):
        """Graceful no-op for callers that don't pass --smm-dir yet."""
        import close_common

        td = self._make_repo("feature.py")
        rc = close_common.cmd_merge(self._make_args(td, None))
        self.assertEqual(rc, 0)
        # No SMM directory means no events.jsonl to inspect — assertion
        # is that cmd_merge did not crash on smm_dir=None.

    def test_merge_dedupes_by_commit_hash(self):
        """A re-merge of the same already-merged source must not duplicate
        the commit event. ``git merge --no-ff`` returns rc=0 with HEAD
        unchanged on "Already up to date", so the helper still runs."""
        import close_common

        td = self._make_repo("feature.py")
        smm_dir = self._make_smm()
        rc = close_common.cmd_merge(self._make_args(td, smm_dir))
        self.assertEqual(rc, 0)
        pre_count = len(self._read_commit_events(smm_dir))
        self.assertEqual(pre_count, 1)

        # cmd_merge deleted the local source on the first run — recreate it
        # pointing at the merge commit so the second merge yields
        # "Already up to date" (HEAD unchanged) and exercises the dedupe.
        subprocess.run(
            ["git", "branch", _SOURCE, "HEAD"],
            cwd=td,
            capture_output=True,
            check=True,
            env=_bf.GIT_ENV,
        )
        rc2 = close_common.cmd_merge(self._make_args(td, smm_dir))
        self.assertEqual(rc2, 0)
        post_count = len(self._read_commit_events(smm_dir))
        self.assertEqual(
            post_count,
            pre_count,
            f"dedupe failed: pre={pre_count} post={post_count}",
        )

    def test_merge_survives_corrupt_sprint_json(self):
        """A corrupt sprint.json must not crash cmd_merge AFTER the merge
        already produced its commit on target — the helper degrades to
        sprint_id-less metadata and the chain continues. Matches
        _verify_gate_block's established fail-open posture for SMM-state
        errors that surface post-merge."""
        import close_common

        td = self._make_repo("feature.py")
        smm_dir = self._make_smm()
        # Corrupt sprint.json — load_sprint raises SprintCorruptError.
        (smm_dir / "sprint.json").write_text("{not valid json", encoding="utf-8")
        rc = close_common.cmd_merge(self._make_args(td, smm_dir))
        self.assertEqual(rc, 0)
        commit_events = self._read_commit_events(smm_dir)
        self.assertEqual(len(commit_events), 1)
        # Degraded: no sprint_id key because the file was unreadable.
        self.assertNotIn("sprint_id", commit_events[0]["metadata"])
        # Story-id still flows from the source branch name (not sprint-derived).
        self.assertEqual(commit_events[0]["metadata"]["story_id"], "story-007")

    def test_merge_failure_no_commit_event(self):
        """branch_lifecycle._merge_into_target sys.exit(1)s on git-merge
        non-zero (lines 64-70). A failed merge must NOT emit a commit."""
        import close_common

        td_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(td_ctx.cleanup)
        td = td_ctx.name
        _bf.init_repo(td)  # no source branch created
        smm_dir = self._make_smm()
        with self.assertRaises(SystemExit):
            close_common.cmd_merge(
                self._make_args(td, smm_dir, source="nonexistent-branch")
            )
        self.assertEqual(len(self._read_commit_events(smm_dir)), 0)


if __name__ == "__main__":
    unittest.main()
