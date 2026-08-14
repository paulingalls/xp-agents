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

WHICH PATH EACH CASE DRIVES, because that was wrong here once. Every case used to
hand `run_hook` a command with no `-m` and an empty `stdout`, while STAGING a
merge that carried one — so the whole suite exercised the rebuild arm, and the two
shapes an operator actually runs were never driven at all. Measured: both of them
are CONFIRMED commits and never reach the rebuild.

  * `git merge --no-ff side -m "Merge side"` prints `Merge made by the 'ort'
    strategy.` and NO `[branch hash]` line, so `parse_commit_message` finds
    nothing — but HEAD's body is the `-m` arg, so `_head_matches_command`
    confirms it. Success path.
  * a conflict finished by `git commit --no-edit` prints
    `[main <hash>] Merge branch 'side'`, which `parse_commit_message` reads
    directly. Success path.
  * only a merge whose stdout reached the hook EMPTY (truncated by a large
    pre-commit hook, or backgrounded) leaves both signals unavailable and falls
    through to the rebuild.

So each positive case is driven twice, once per route, and git's real stdout is
CAPTURED from the command rather than spelled as a literal — a hardcoded
`'ort' strategy` string would rot on a git that renames its default strategy, and
the stale-literal problem is what this suite already exists to catch.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _commit_repo_case import _MergeCase


class TestAMergeCommitIsRecorded(_MergeCase):
    def _assert_one_merge_event(self) -> dict:
        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertTrue(
            events[0]["metadata"].get("is_merge"),
            "the merge HEAD was recorded as a plain commit",
        )
        return events[0]

    def test_the_merge_an_operator_actually_runs_is_tagged(self):
        """THE SHAPE PRODUCTION TAKES: `-m` on the command line, confirmed
        because HEAD's body equals that arg, so the rebuild is never reached.

        The tag is what keeps the event out of the resolves-link-rate
        denominator, so a merge cannot dilute a rate it carries no trailer for —
        and it is what exempts the event from the commit-size concern, since a
        merge's `files` is legitimately the whole merged branch.
        """
        self.diverge()
        result = self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.parent_count(), 2, "expected a real merge commit")
        self.assertNotIn(
            "[", result.stdout, "a merge prints no `[branch hash]` line; premise"
        )

        self.run_hook('git merge --no-ff side -m "Merge side"', result.stdout)

        self._assert_one_merge_event()

    def test_a_merge_whose_stdout_never_arrived_is_tagged(self):
        """The same merge via the OTHER route — the rebuild arm. Both signals
        are unavailable (no readable `-m`, empty stdout), which is what a
        truncating pre-commit hook or a backgrounded run leaves behind."""
        self.diverge()
        self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(self.parent_count(), 2, "expected a real merge commit")

        self.run_hook("git merge --no-ff side")

        self._assert_one_merge_event()

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

    def _finish_a_conflict_by_hand(self) -> str:
        """Resolve a conflicted merge and commit it. Returns git's real stdout.

        No `-q`: the `[branch hash]` line it suppresses is the whole point — that
        line is what confirms the commit on the success path, so a quiet finish
        would hand the hook an empty stdout and silently test the rebuild arm
        instead.
        """
        self.diverge(same_file=True)
        self.assertNotEqual(self.merge("side").returncode, 0, "expected a conflict")
        (self.repo / "src" / "side.py").write_text("resolved\n")
        self.git("add", "-A")
        stdout = self.git("commit", "--no-edit")
        self.assertEqual(self.parent_count(), 2, "expected a real merge commit")
        action = self.git("reflog", "-1", "--format=%gs")
        self.assertTrue(action.startswith("commit (merge)"), f"reflog: {action!r}")
        return stdout

    def test_a_conflict_finished_by_hand_is_tagged(self):
        """The other spelling, and the landing with the STRONGEST attribution:
        the operator resolved a conflict and finished the merge with
        `git commit`, so the command really is what produced HEAD. git spells
        that reflog `commit (merge)` (`merge --continue` measured the same), a
        leading word of `commit` the merge test above cannot see — while
        `git_commits` keeps `merge --continue` gated as commit-producing.

        Driven with git's `[branch hash]` line, so this is the SUCCESS path —
        the route an operator's conflict finish really takes.
        """
        stdout = self._finish_a_conflict_by_hand()
        self.assertIn("[", stdout, "expected git's `[branch hash]` line; premise")

        self.run_hook("git commit --no-edit", stdout)

        self._assert_one_merge_event()

    def test_a_conflict_finish_whose_stdout_never_arrived_is_tagged(self):
        """The same landing via the rebuild arm, for the truncated-stdout case."""
        self._finish_a_conflict_by_hand()

        self.run_hook("git commit --no-edit")

        self._assert_one_merge_event()


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
        """The freshness bound, ISOLATED — it is what stops the hook claiming
        history someone else wrote. Backdating with `commit --amend` would not
        isolate it: that rewrites the reflog action to `commit (amend)`, which
        the merge arm refuses anyway, so the case stayed green with the age
        bound deleted. A merge CREATED with old dates still reflogs
        `merge side` (measured), leaving age as the only signal left to refuse.
        """
        self.diverge()
        stamp = "1000000000 +0000"
        result = self.merge(
            "--no-ff",
            "side",
            "-m",
            "Merge side",
            env_extra={"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        action = self.git("reflog", "-1", "--format=%gs")
        self.assertTrue(action.startswith("merge "), f"reflog: {action!r}")

        self.run_hook("git merge --no-ff side")
        self.assertEqual(self.merge_events(), [])


class TestThePlainCommitPathIsUnchanged(_MergeCase):
    def test_a_single_parent_commit_is_recorded_without_the_merge_tag(self):
        """The POSITIVE control for the plain arm: the same unreadable command
        over a one-parent HEAD still records, and the event carries no
        `is_merge`. Asserting only "nothing was tagged a merge" would also pass
        on an empty log — which is how a broken plain arm reads. The
        reset/amend-reached HEADs the old veto protected are refused on the
        reflog action, and `test_commit_event_rebuild` pins each of them."""
        self.commit("feat: ordinary work")
        self.run_hook('git commit -m "$UNREADABLE"')
        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertNotIn("is_merge", events[0]["metadata"])


if __name__ == "__main__":
    unittest.main()
