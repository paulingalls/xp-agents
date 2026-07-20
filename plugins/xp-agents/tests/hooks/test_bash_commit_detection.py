#!/usr/bin/env python3
"""Tests for bash_post_tool commit-detection edge cases: truncated
pre-commit-hook stdout (HEAD-body fallback matching) and free-session
branch tagging on commit events.

Split from test_bash_commit.py to stay under the file-size cap; see that
file's docstring for the sibling map.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_post_tool
from _commit_helpers import patch_commits
from conftest import _HookTestCase, _make_bash_input, make_event
from event_helpers import events_of_type
from event_schema import (
    EVENT_TYPE_COMMIT,
)


class TestBashPostToolTruncatedStdout(_HookTestCase):
    """Large pre-commit hook output (Husky lint-staged + tsc + bun test, etc.)
    can push the Bash tool's stdout past its truncation cap, slicing off the
    trailing `[branch hash] msg` line. The hook must still recognise the
    commit by comparing the `-m` arg against HEAD's body.
    """

    _TRUNCATED = "$ bun run tsc --noEmit\n" + "test output line\n" * 1000

    def test_truncated_stdout_records_commit_via_head_match(self):
        """Truncated stdout + HEAD body matches the -m message → commit recorded."""
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat(x): real subject\n"
            "\n"
            "body text\n"
            "EOF\n"
            ')"'
        )
        with patch_commits(
            files=["src/foo.py"],
            body="feat(x): real subject\n\nbody text",
            head_sha="abc123def",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=self._TRUNCATED),
                smm_dir=self.smm_dir,
            )
        recorded = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(
            recorded[0]["content"].split("\n", 1)[0],
            "feat(x): real subject",
        )

    def test_truncated_stdout_no_event_when_head_does_not_match(self):
        """Truncated stdout + HEAD body unchanged (pre-commit rejected) → no event.

        Guards the fallback path against over-recording: when stdout doesn't
        prove success AND HEAD's body doesn't match what we asked git to
        commit, we must NOT invent a commit event. Pre-fix this returned the
        same outcome (None) via the stdout-only check; post-fix it returns
        None via the combined-signal check. The behavior contract is what's
        load-bearing, not which branch produced it.
        """
        command = "git commit -m 'feat: new feature'"
        with patch_commits(
            files=[],
            body="some older commit message",
            head_sha="oldhash",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=self._TRUNCATED),
                smm_dir=self.smm_dir,
            )
        recorded = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(recorded), 0)

    def test_truncated_stdout_simple_quoted_message_matches(self):
        """Simple -m 'msg' shape also works when stdout is truncated."""
        command = "git commit -m 'fix(bug): patch issue'"
        with patch_commits(
            files=["src/foo.py"],
            body="fix(bug): patch issue",
            head_sha="newhash",
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=self._TRUNCATED),
                smm_dir=self.smm_dir,
            )
        recorded = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(recorded), 1)

    def _seed_existing_commit(self, head_sha: str) -> dict:
        existing = make_event(
            EVENT_TYPE_COMMIT,
            content="feat(x): real subject",
            metadata={"commit_hash": head_sha, "action": "commit_success"},
            files=["src/foo.py"],
        )
        _common.append_safe(self.smm_dir, existing)
        return existing

    def test_truncated_stdout_skips_duplicate_when_hash_already_recorded(self):
        """Fallback path: HEAD unchanged + last commit event carries this
        hash → no duplicate event.

        Guards the fallback: `_head_matches_command` only proves "HEAD's
        subject matches the -m arg", not "a NEW commit landed". When HEAD
        hasn't moved since the last recorded commit event, the apparent
        match is the *prior* successful commit, not a fresh one.
        """
        head_sha = "abc123def456"
        existing = self._seed_existing_commit(head_sha)

        command = "git commit -m 'feat(x): real subject'"
        with patch_commits(
            files=["src/foo.py"],
            body="feat(x): real subject",
            head_sha=head_sha,
        ):
            bash_post_tool.run(
                _make_bash_input(command=command, stdout=self._TRUNCATED),
                smm_dir=self.smm_dir,
            )
        recorded = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["id"], existing["id"])

    def test_parse_commit_message_skips_duplicate_when_hash_already_recorded(self):
        """Primary path: stdout has `[branch hash] msg` but HEAD still
        carries a hash we already recorded (stale stdout echoed back, e.g.
        via tee or a chained command). Dedupe is path-agnostic.
        """
        head_sha = "abc123def456"
        existing = self._seed_existing_commit(head_sha)

        command = "git commit -m 'feat(x): real subject'"
        with patch_commits(
            files=["src/foo.py"],
            body="feat(x): real subject",
            head_sha=head_sha,
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command=command,
                    stdout="[main abc1234] feat(x): real subject\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        recorded = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["id"], existing["id"])


class TestBashPostToolFreeSessionTag(_HookTestCase):
    """Commits on a free branch (`<user>/free-YYYY-MM-DD-<slug>`) tag the
    emitted commit event with ``metadata.is_free_session=True``. Honored
    by ``retro_metrics._compute_resolves_link_rate`` as a conditional
    exclusion (exploration commits without trailers drop out of the rate).
    """

    def test_free_branch_commit_tagged_is_free_session(self):
        with (
            patch_commits(
                files=["scripts/x.py"],
                body="explore",
                head_sha="freebranch1234",
            ),
            patch(
                "identity.get_current_branch",
                return_value="paulingalls/free-2026-05-23-explore",
            ),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'explore'",
                    stdout=(
                        "[paulingalls/free-2026-05-23-explore freebranch] "
                        "explore\n 1 file changed"
                    ),
                ),
                smm_dir=self.smm_dir,
            )
        commit_events = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_events), 1)
        self.assertTrue((commit_events[0].get("metadata") or {}).get("is_free_session"))

    def test_main_branch_commit_not_tagged(self):
        with (
            patch_commits(
                files=["scripts/x.py"],
                body="mainline",
                head_sha="mainbranch1234",
            ),
            patch("identity.get_current_branch", return_value="main"),
        ):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'mainline'",
                    stdout="[main mainbranch] mainline\n 1 file changed",
                ),
                smm_dir=self.smm_dir,
            )
        commit_events = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(len(commit_events), 1)
        self.assertNotIn("is_free_session", commit_events[0].get("metadata") or {})


if __name__ == "__main__":
    unittest.main()
