#!/usr/bin/env python3
"""A hand-run `git merge` should leave a commit event behind.

`append_merge_commit_event` closes this hole for the merges the plugin performs
itself (`close_common.cmd_merge`), and its docstring calls the unrecorded merge
"the merge-gap commit-event hole". The hand-run case was never wired — the
rebuild path reaches a merge HEAD (a merge supplies no message, so
`_message_unreadable_from_command` is True) and then stops at one line:
`if parent_count > 1: return False`.

That veto's comment argued merges are "not this command's work at all", which is
true when the command is `git commit` and false when it is `git merge`. The
reflog already says which happened, and the rebuild's own docstring is explicit
that its claim is "a commit exists at this hash with no event, and here is its
message read back from git" — NOT "this command produced it". So the reflog
action is the whole question and no command inspection is needed.

THE TRAP THIS SUITE EXISTS TO PIN: `head_landing_facts` keeps everything before
the colon in `%gs`, and git spells a merge `merge side: Merge made by the 'ort'
strategy.` — so `action == "merge"` never matches. A predicate written that way
records nothing and, because this path fails closed, looks correct. The shared
fixture's own `erase_reflog` docstring measured the same string.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _commit_repo_case import _RebuildTestCase


class _MergeCase(_RebuildTestCase):
    """A repo with a divergent side branch, ready to merge."""

    def diverge(self, *, same_file: bool = False) -> None:
        """Create `side` with a commit, and advance `main` too.

        `same_file=True` makes the two edits collide, which is how a conflicted
        merge is produced — the case where HEAD must NOT move.
        """
        self.git("checkout", "-q", "-b", "side")
        self.commit("side work", path="src/side.py", content="side")
        self.git("checkout", "-q", "main")
        self.commit(
            "main work",
            path="src/side.py" if same_file else "src/main.py",
            content="main",
        )

    def merge(self, *args: str) -> subprocess.CompletedProcess:
        """Run a merge that is ALLOWED to fail (a conflict is a test case)."""
        return subprocess.run(
            ["git", "merge", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def parent_count(self) -> int:
        return len(self.git("show", "-s", "--format=%P", "HEAD").split())

    def merge_events(self) -> list[dict]:
        """Commit events claiming a MERGE, which is all these cases assert on.

        Not `commit_events() == []`: the fixture's own setup commits leave a
        young single-parent HEAD with reflog action `commit`, so the PLAIN
        rebuild arm legitimately records one. That is pre-existing behaviour and
        not what any case here is about — the question is only ever whether a
        merge was claimed.
        """
        return [e for e in self.commit_events() if e["metadata"].get("is_merge")]


class TestAMergeCommitIsRecorded(_MergeCase):
    def test_the_event_lands_and_is_tagged_as_a_merge(self):
        """The tag is what keeps the event out of the resolves-link-rate
        denominator, so a merge cannot dilute a rate it carries no trailer for."""
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(self.parent_count(), 2, "expected a real merge commit")

        self.run_hook("git merge --no-ff side")

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertTrue(events[0]["metadata"].get("is_merge"))

    def test_the_event_carries_the_message_git_stored(self):
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side into main")
        self.run_hook("git merge --no-ff side")
        self.assertIn("Merge side into main", self.commit_events()[0]["content"])

    def test_the_reflog_action_is_matched_by_leading_word(self):
        """`%gs` spells it `merge side: ...`, so an equality test against
        "merge" is inert. Assert the real string shape, then the outcome."""
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side")
        action = self.git("reflog", "-1", "--format=%gs")
        self.assertTrue(action.startswith("merge "), f"unexpected reflog: {action!r}")
        self.assertNotEqual(action.split(":", 1)[0], "merge")

        self.run_hook("git merge --no-ff side")
        self.assertEqual(len(self.commit_events()), 1)


class TestTheCasesThatMustClaimNothing(_MergeCase):
    def test_a_conflicted_merge_records_no_commit_event(self):
        """HEAD never moved, so there is nothing to record."""
        self.diverge(same_file=True)
        before = self.head()
        result = self.merge("side")
        self.assertNotEqual(result.returncode, 0, "expected a conflict")
        self.assertEqual(self.head(), before)

        self.run_hook("git merge side")
        self.assertEqual(self.merge_events(), [])

    def test_a_fast_forward_records_no_commit_event(self):
        """A fast-forward creates no commit — HEAD moves onto someone else's."""
        self.git("checkout", "-q", "-b", "side")
        self.commit("side work", path="src/side.py", content="side")
        self.git("checkout", "-q", "main")
        self.merge("side")
        self.assertEqual(self.parent_count(), 1)

        self.run_hook("git merge side")
        self.assertEqual(self.merge_events(), [])

    def test_an_unreadable_reflog_records_no_commit_event(self):
        """Fail closed, exactly as the plain-commit arm does: absence vetoes
        rather than letting freshness and parent count stand alone."""
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side")
        self.erase_reflog()

        self.run_hook("git merge --no-ff side")
        self.assertEqual(self.merge_events(), [])

    def test_a_stale_merge_head_records_no_commit_event(self):
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side")
        # Rewrite the merge with an old committer date; the freshness bound is
        # what stops claiming history someone else wrote.
        self.git(
            "commit",
            "--amend",
            "--no-edit",
            "-q",
            env_extra={
                "GIT_COMMITTER_DATE": "1000000000 +0000",
                "GIT_AUTHOR_DATE": "1000000000 +0000",
            },
        )

        self.run_hook("git merge --no-ff side")
        self.assertEqual(self.merge_events(), [])


class TestThePlainCommitPathIsUnchanged(_MergeCase):
    def test_a_single_parent_commit_still_takes_the_ordinary_arm(self):
        """The merge arm must not swallow the case the veto was protecting: a
        young single-parent HEAD reached by something other than committing."""
        self.commit("feat: ordinary work")
        self.git("reset", "-q", "--hard", "HEAD")
        self.run_hook('git commit -m "$UNREADABLE"')
        events = self.commit_events()
        for event in events:
            self.assertFalse(event["metadata"].get("is_merge"))


if __name__ == "__main__":
    unittest.main()
