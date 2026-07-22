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
import bash_post_tool
import commit_handling
from _bases import _AssertNotNoneMixin
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN


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

    def test_redirect_after_delimiter_still_parses(self):
        """AC-1: a redirect on the same line as the opening delimiter is a
        legal shell suffix (`<<'EOF' > /dev/null`) — the old pattern demanded
        the newline immediately after the delimiter and returned None."""
        import commits

        command = "git commit -q -F - <<'EOF' > /dev/null\nfeat: redirected\nEOF"
        self.assertEqual(commits.extract_commit_message(command), "feat: redirected")

    def test_pipe_and_chain_after_delimiter_still_parses(self):
        """AC-2: a pipe plus a chained command after the opening delimiter
        (`<<'EOF' | cat && echo done`) — story-005's actual command shape
        (concern 1e6186970e01)."""
        import commits

        command = (
            "git commit -q -F - <<'EOF' | cat && echo done\n"
            "feat: piped and chained\nEOF"
        )
        self.assertEqual(
            commits.extract_commit_message(command), "feat: piped and chained"
        )

    def test_binds_to_dash_F_heredoc_even_when_earlier_heredoc_has_trailing_redirect(
        self,
    ):
        """AC-4, asserted explicitly: the looser opening pattern now admits a
        trailing redirect on ANY heredoc line, not just the message's — so an
        earlier, unrelated heredoc with its own trailing redirect must still
        be skipped in favor of the one introduced after `-F -`. Guards the
        `stdin_flag.end()` search-start boundary against the new pattern."""
        import commits

        command = (
            "cat <<CFG > config.txt\nkey=val\nCFG\n"
            "git commit -q -F - <<'MSG'\nfeat: real subject\nMSG"
        )
        self.assertEqual(commits.extract_commit_message(command), "feat: real subject")


class TestHeadMovedUnparsedTrace(_HookTestCase):
    """Story-009: when a commit-shaped command's message did not parse
    (`_confirm_commit_repo` returns `(None, "")`) and the `-C` target is not
    an unreachable shell-variable path, disambiguate a pre-commit rejection
    (HEAD unchanged) from an unparsed success (HEAD advanced past what's
    recorded) by re-probing HEAD from the command's own repo.
    """

    _UNMATCHED_COMMAND = "git commit -m 'feat: unparseable subject'"

    def test_unparsed_success_head_moved_records_trace(self):
        """AC-1: HEAD advanced to a commit hash with no recorded event →
        exactly one low trace naming the command."""
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)
        self.assertIn("feat: unparseable subject", traces[0]["content"])
        self.assertEqual(traces[0].get("severity"), "low")

    def test_prior_rejection_head_unchanged_records_nothing(self):
        """AC-2: HEAD sits at an already-recorded commit (pre-commit
        rejection left history untouched) → no new event."""
        head_sha = "alreadyrecorded123"
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="feat(x): prior work",
                metadata={"commit_hash": head_sha, "action": "commit_success"},
                files=["src/foo.py"],
            ),
        )
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha=head_sha,
        ):
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 0)

    def test_dash_c_unreachable_path_unchanged_no_duplicate(self):
        """AC-3: the `-C "$VAR"` hidden-path case still records via
        `_record_unconfirmed_commit` and returns before the HEAD-moved
        block runs — exactly one event, not two."""
        command = "git -C \"$WT\" commit -m 'feat: unparseable subject'"
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)
        self.assertIn("could not confirm which repository", traces[0]["content"])

    def test_head_unreadable_degrades_quietly(self):
        """AC-4: `get_head_commit_hash` returns None (probe cwd isn't a
        repo) → no event, no exception."""
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha=None,
        ):
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 0)

    def test_trace_wording_does_not_claim_success(self):
        """Honest-observation pin: the trace states HEAD points at an
        unrecorded commit, never that the commit 'landed' or 'succeeded' —
        the observation is real, the inference is not."""
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)
        content = traces[0]["content"].lower()
        self.assertNotIn("landed", content)
        self.assertNotIn("succeeded", content)

    def test_commit_reuse_message_dash_C_still_traces(self):
        """The `-C <commit>` reuse-message flag is NOT the `git -C <path>`
        change-directory flag: it runs in the ordinary cwd, so an unparsed
        success there must still record a HEAD-moved trace. The gate keys on
        the git-global `-C` only, not any `-C` token."""
        command = "git commit -C HEAD"
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)

    def test_dash_C_inside_message_body_still_traces(self):
        """A `-C ` substring inside the commit message must not be misread as
        a `git -C <path>` flag and suppress the trace — the gate is anchored
        to `git ... -C`, not to any raw `-C` token."""
        command = "git commit -m 'refactor -C flag parsing'"
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)

    def test_literal_dash_C_path_suppressed_no_trace(self):
        """A `git -C <literal-path>` that failed to confirm is an ordinary git
        failure (git aborts, lands nothing) — suppress silently rather than
        probe the ORCHESTRATOR cwd's unrelated HEAD. Covers the suppress branch
        the other `-C` tests deliberately dodge."""
        command = "git -C /nonexistent/repo commit -m 'feat: unparseable subject'"
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 0)

    def test_dash_C_git_in_message_body_still_traces(self):
        """A commit message that MENTIONS `git -C` (routine in a git-tooling
        repo) must not be misread as a `git -C <path>` invocation and
        suppressed. The gate scans the quote-stripped command, so message-body
        text — even a full `git -C /path` phrase — can never gate it."""
        command = "git commit -m 'docs: prefer git -C over cd for worktrees'"
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)


if __name__ == "__main__":
    unittest.main()
