#!/usr/bin/env python3
"""Story-009: telling a rejected commit apart from an unparsed successful one.

Split from `test_commit_handling.py` (551 lines). When a commit-shaped command's
message does not parse, the hook cannot record an event — and the two reasons for
that look identical from outside: a pre-commit hook rejected the commit (HEAD
unchanged), or the commit LANDED and only the message parse failed (HEAD advanced
past what is recorded). Re-probing HEAD from the command's own repo is what
separates them.

Grouped away from the builder and message-extraction tests because the subject is
not a shape or a parse: it is what to do once the parse has already failed, which
is why almost every test here is about the trace's wording and its dedup rather
than about commits.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT, EVENT_TYPE_CONCERN


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

    def test_config_flag_before_dash_C_nonexistent_path_suppressed(self):
        """Finding #1: the CI-identity `git -c key=val -C <literal-path>` form
        must still be recognized as `-C`-targeted and suppressed when the path
        is unreachable. The `-c commit.gpgsign=false` config token doesn't
        start with `-`, so the old `(?:-\\S+\\s+)*?` chain stalled on it, missed
        the `-C`, and probed the ORCHESTRATOR's HEAD — the exact misread the
        gate exists to prevent."""
        command = (
            "git -c commit.gpgsign=false -C /nonexistent/repo commit "
            "-m 'feat: unparseable subject'"
        )
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

    def test_reachable_dash_C_landed_commit_still_traces(self):
        """Finding #2: a `git -C <reachable> commit` that LANDED but whose
        message a commit-msg hook rewrote fails confirmation. The gate must NOT
        blanket-suppress it — probe HEAD from the `-C` target's own repo so an
        unparsed success there is still traced. `/tmp` stands in for a reachable
        target."""
        command = (
            "git -c commit.gpgsign=false -C /tmp commit -m 'feat: unparseable subject'"
        )
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout="", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)

    def test_repeated_unparsed_head_moved_dedups_trace(self):
        """Finding #3: re-running the same failing commit-shaped command while
        HEAD still points at the same unrecorded commit (a rejected pre-commit
        that keeps getting retried) must not append a second identical trace —
        the dedup keys on the HEAD hash stamped into the trace metadata."""
        with patch_commits(
            files=["src/foo.py"],
            body="a different subject entirely",
            head_sha="movedhash123",
        ):
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
            bash_post_tool.run(
                _make_bash_input(command=self._UNMATCHED_COMMAND, stdout=""),
                smm_dir=self.smm_dir,
            )
        traces = events_of_type(self._read_events(), EVENT_TYPE_CONCERN)
        self.assertEqual(len(traces), 1)


if __name__ == "__main__":
    unittest.main()
