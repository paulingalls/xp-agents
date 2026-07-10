#!/usr/bin/env python3
"""Unit tests for commit_handling.make_commit_event.

The shared commit-event builder consolidates the metadata shape between
bash-commit emissions (_handle_commit) and close-cycle merge emissions
(merge_commit_event.append_merge_commit_event). Pinning its contract here
keeps the two callers honest — if either side drifts, the unit fails
before the integration paths do (close-review concern ac839221498c).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import commit_handling
from _bases import _AssertNotNoneMixin


class TestMakeCommitEvent(unittest.TestCase):
    """Pin the shared commit-event builder's output shape across both
    call paths (bash commit, close-cycle merge). Drift between the two
    callers is the failure mode this primitive prevents."""

    def test_minimal_event(self):
        """The smallest valid commit event has the action + code-commit
        triple plus the commit_hash; no optional keys leak in."""
        ev = commit_handling.make_commit_event(
            "main",
            "fix: x",
            commit_hash="abc1234",
            files=["a.py"],
            code_file_count=1,
        )
        self.assertEqual(ev["type"], _common.COMMIT)
        self.assertEqual(ev["agent_id"], "main")
        self.assertEqual(ev["content"], "fix: x")
        self.assertEqual(ev["files"], ["a.py"])
        meta = ev["metadata"]
        self.assertEqual(meta["action"], "commit_success")
        self.assertTrue(meta["code_commit"])
        self.assertEqual(meta["code_file_count"], 1)
        self.assertEqual(meta["commit_hash"], "abc1234")
        # Optional keys absent when not passed.
        for key in (
            "resolves",
            "has_resolves_trailer",
            "story_id",
            "sprint_id",
            "is_merge",
        ):
            self.assertNotIn(key, meta, f"unexpected metadata key: {key}")

    def test_bash_commit_shape(self):
        """_handle_commit's call shape: trailer-derived resolves +
        has_resolves_trailer + story_id + sprint_id, no is_merge."""
        ev = commit_handling.make_commit_event(
            "worktree-story-007",
            "story-007: feat\n\nResolves-Event: deadbeef0000",
            commit_hash="abc1234",
            files=["a.py", "test_a.py"],
            code_file_count=2,
            story_id="story-007",
            sprint_id="sprint-097",
            resolves=["deadbeef0000"],
            has_resolves_trailer=True,
        )
        meta = ev["metadata"]
        self.assertEqual(meta["resolves"], ["deadbeef0000"])
        self.assertTrue(meta["has_resolves_trailer"])
        self.assertEqual(meta["story_id"], "story-007")
        self.assertEqual(meta["sprint_id"], "sprint-097")
        self.assertNotIn("is_merge", meta)
        self.assertEqual(meta["code_file_count"], 2)

    def test_merge_commit_shape(self):
        """close_common's call shape: is_merge=True, no resolves trailer,
        story_id derived from source branch identity."""
        ev = commit_handling.make_commit_event(
            "close_common",
            "Merge paul/story-007-demo",
            commit_hash="def5678",
            files=["scripts/x.py"],
            code_file_count=1,
            story_id="story-007",
            sprint_id="sprint-097",
            is_merge=True,
        )
        meta = ev["metadata"]
        self.assertTrue(meta["is_merge"])
        self.assertEqual(meta["story_id"], "story-007")
        self.assertEqual(meta["sprint_id"], "sprint-097")
        self.assertNotIn("resolves", meta)
        self.assertNotIn("has_resolves_trailer", meta)

    def test_docs_only_commit_clears_code_flag(self):
        """code_file_count=0 → code_commit=False (the doc-only commit
        shape used by retro_metrics to exclude prose commits)."""
        ev = commit_handling.make_commit_event(
            "main",
            "docs: README",
            commit_hash="abc1234",
            files=["README.md"],
            code_file_count=0,
        )
        meta = ev["metadata"]
        self.assertFalse(meta["code_commit"])
        self.assertEqual(meta["code_file_count"], 0)

    def test_free_session_shape(self):
        """is_free_session=True tags metadata.is_free_session; default omits
        the key. Mirror of is_merge — the rate filter applies conditional
        include based on trailer presence (test pinned in test_retro_metrics).
        """
        ev = commit_handling.make_commit_event(
            "main",
            "free-session work",
            commit_hash="abc1234",
            files=["scripts/x.py"],
            code_file_count=1,
            is_free_session=True,
        )
        self.assertTrue(ev["metadata"]["is_free_session"])

        ev_default = commit_handling.make_commit_event(
            "main",
            "regular work",
            commit_hash="abc1234",
            files=["scripts/x.py"],
            code_file_count=1,
        )
        self.assertNotIn("is_free_session", ev_default["metadata"])

    def test_story_cadence_shape(self):
        """review_cadence="story" tags metadata.review_cadence; the default
        (commit cadence) omits the key. Mirror of is_free_session — only the
        non-default lands, keeping events lean. Honored by
        honesty_signals as a review-required exemption (story commits defer
        their review to /xp-story-close)."""
        ev = commit_handling.make_commit_event(
            "main",
            "story step",
            commit_hash="abc1234",
            files=["scripts/x.py"],
            code_file_count=3,
            review_cadence="story",
        )
        self.assertEqual(ev["metadata"]["review_cadence"], "story")

        ev_default = commit_handling.make_commit_event(
            "main",
            "commit-cadence work",
            commit_hash="abc1234",
            files=["scripts/x.py"],
            code_file_count=3,
            review_cadence="commit",
        )
        self.assertNotIn("review_cadence", ev_default["metadata"])

        ev_unset = commit_handling.make_commit_event(
            "main",
            "untagged work",
            commit_hash="abc1234",
            files=["scripts/x.py"],
            code_file_count=3,
        )
        self.assertNotIn("review_cadence", ev_unset["metadata"])

    def test_no_commit_hash_omits_key(self):
        """commit_hash=None → key omitted (not stored as None) so
        downstream dedupe-by-hash matchers see absence, not a None
        value to special-case."""
        ev = commit_handling.make_commit_event(
            "main",
            "body",
            commit_hash=None,
            files=[],
            code_file_count=0,
        )
        self.assertNotIn("commit_hash", ev["metadata"])

    def test_empty_sprint_id_still_emitted(self):
        """sprint_id="" (the empty_sprint() initial state) still lands
        on the event — matches the pre-extraction
        ``if sprint is not None`` idiom. Truthy-checking would silently
        drop it; the absent-vs-empty distinction matters to compact.py
        retention scans that filter by metadata.sprint_id membership."""
        ev = commit_handling.make_commit_event(
            "main",
            "body",
            commit_hash="abc1234",
            files=["a.py"],
            code_file_count=1,
            sprint_id="",
        )
        self.assertIn("sprint_id", ev["metadata"])
        self.assertEqual(ev["metadata"]["sprint_id"], "")


class TestExtractCommitMessageFileRobustness(_AssertNotNoneMixin, unittest.TestCase):
    """The `-F <path>` branch reads a message file to confirm the commit.

    A commit message with non-UTF-8 bytes (e.g. a latin-1 author name) must
    NOT crash the PostToolUse:Bash hook — a decode error is a ValueError, not
    an OSError, so it escaped the read-failure suppress and propagated out of
    `run()`, violating "a hook must not break the user's commit"."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_non_utf8_message_file_does_not_raise(self):
        import commits

        msg_file = self.dir / "MSG"
        msg_file.write_bytes(b"fix: caf\xe9 handling\n")  # 0xe9 invalid UTF-8
        # Must return a (best-effort) string, never raise UnicodeDecodeError:
        # that is a ValueError, not an OSError, so it would escape the
        # suppress and crash a hook that fires on every Bash call.
        result = self._assert_not_none(
            commits.extract_commit_message(f"git commit -F {msg_file}")
        )
        self.assertIn("fix: caf", result)

    def test_missing_message_file_returns_none(self):
        import commits

        result = commits.extract_commit_message(
            f"git commit -F {self.dir / 'does-not-exist'}"
        )
        self.assertIsNone(result)


class TestExtractCommitMessageStdinHeredoc(unittest.TestCase):
    """`-F -` reads the message from stdin — in practice a heredoc appended to
    the command. Finding 6: when the command line ALSO opens an earlier,
    unrelated heredoc (e.g. writing a config file), the message must bind to
    the heredoc introduced after `-F -`, not merely the first one in the
    string — otherwise the subject comparison fails and the real commit
    (with any Resolves trailer it carried) is dropped from the event log."""

    def test_binds_to_dash_F_heredoc_not_an_earlier_one(self):
        import commits

        command = (
            "cat <<CFG\nkey=val\nCFG\n"
            "git commit -q -F - <<'MSG'\nfeat: real subject\nMSG"
        )
        self.assertEqual(commits.extract_commit_message(command), "feat: real subject")

    def test_single_stdin_heredoc_still_parses(self):
        import commits

        command = "git commit -q -F - <<'MSG'\nfeat: only one\nMSG"
        self.assertEqual(commits.extract_commit_message(command), "feat: only one")


if __name__ == "__main__":
    unittest.main()
