#!/usr/bin/env python3
"""Converge `append_merge_commit_event` on its sibling's is_merge + content rule.

story-005: the close-cycle emitter hardcoded `is_merge=True` — false when
`branching.merge_branch` succeeds on "Already up to date" and creates no
commit, leaving HEAD on a plain single-parent commit that then gets
mis-tagged as a merge. It also stored the RAW commit body instead of the
cleaned one both hook routes (`commit_emit.build_commit_event`) already
store. `commit_emit.py:196-212` already derives `is_merge` from the parent
count and cleans the body via `parse_commit_body` — this suite pins that
`append_merge_commit_event` now does the same, rather than inventing a
second answer.

A new file rather than an addition to `test_process_commit_response_merge.py`
(the file that actually drives this function): that file sits at 435 lines
against the 450-line band floor, so a new class would push it into the band.
Splitting by question is this repo's convention — `test_merge_event_contents.py`
was itself split off for the same reason.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import commit_emit
from _commit_repo_case import _MergeCase
from merge_commit_event import append_merge_commit_event


class TestIsMergeIsDerivedNotHardcoded(_MergeCase):
    """AC1 + AC3: `is_merge` reflects HEAD's actual parent count."""

    def test_already_up_to_date_head_is_not_tagged_a_merge(self):
        """ "Already up to date" creates no commit — HEAD is the PRIOR, plain
        commit. If that commit's own event never landed (the reachable case:
        dedup at :79-84 only blocks when HEAD already carries a commit event),
        this emitter must not tag it as a merge just because it ran after a
        `branching.merge_branch` call."""
        debt_id = self.seed_concern()
        self.commit(
            f"teammate work\n\nResolves-Event: {debt_id}",
            path="src/teammate.py",
            content="x",
        )
        self.assertEqual(self.parent_count(), 1, "premise: a plain commit")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-x-something"
        )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        meta = events[0]["metadata"]
        self.assertNotIn(
            "is_merge", meta, "a plain single-parent HEAD must not be tagged a merge"
        )
        # The only coverage the merge_resolves gating gets: merged_range_commits
        # has no ^2 to read on a single-parent HEAD, so this can't distinguish
        # gated-vs-not on its own, but it pins that the authored id survives.
        self.assertEqual(meta.get("resolves"), [debt_id])

    def test_a_genuine_two_parent_merge_is_still_tagged(self):
        """Positive control: without it, the story could 'pass' by hardcoding
        `is_merge=False` instead of `True`."""
        self.diverge()
        result = self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.parent_count(), 2, "premise: a real merge commit")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-side"
        )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        self.assertTrue(events[0]["metadata"].get("is_merge"))

    def test_an_unknown_parent_count_leaves_the_event_untagged(self):
        """Fail-safe direction, pinned deliberately: an untagged merge is only
        over-counted in a rate, while a wrongly-tagged plain commit is silently
        exempt from the commit-size concern."""
        self.commit("plain work", path="src/plain.py", content="x")

        with patch("commits.head_parent_count", return_value=None):
            append_merge_commit_event(
                str(self.repo), self.smm_dir, "paulingalls/story-unknown"
            )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        self.assertNotIn("is_merge", events[0]["metadata"])

    def test_a_root_commit_is_not_tagged(self):
        """`is None`, not truthiness: a root commit's `%P` is legitimately
        empty, and a truthiness rewrite would call it unknowable instead."""
        self.assertEqual(self.parent_count(), 0, "premise: HEAD is still the root")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-root"
        )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        self.assertNotIn("is_merge", events[0]["metadata"])


class TestContentIsTheCleanedBody(_MergeCase):
    """AC2: stored content is `commit_emit.parse_commit_body`'s cleaned body,
    not the raw body — and matches what the hook routes store for it."""

    def test_the_stored_content_is_the_cleaned_body(self):
        debt_id = self.seed_concern()
        raw_body = (
            f"fix: make it fast\n\n"
            f"Resolves-Event: {debt_id}\n\n"
            f"Co-Authored-By: Bob <bob@example.com>"
        )
        self.commit(raw_body, path="src/fix.py", content="x")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-clean"
        )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        expected = commit_emit.parse_commit_body(raw_body)[1]
        self.assertEqual(events[0]["content"], expected)
        self.assertNotIn("Resolves-Event", events[0]["content"])
        self.assertNotIn("Co-Authored-By", events[0]["content"])

    def test_the_content_matches_what_the_hook_route_stores_for_the_same_body(self):
        """The strongest form available: the two emitters' stored content for
        one identical non-degenerate body must be EQUAL, not a literal
        asserted independently in each. The fixtures necessarily differ — the
        close emitter reads HEAD via `get_commit_message_body`, the hook route
        confirms via git's `[branch hash]` stdout line — so if they disagree
        here it pins a difference in test setup, not in convergence."""
        derived_id = self.seed_concern()
        authored_id = self.seed_concern()
        body = (
            f"Merge branch 'side'\n\n"
            f"Resolves-Event: {authored_id}\n\n"
            f"Co-Authored-By: Bob <bob@example.com>"
        )

        # Hook route: a conflicted merge finished by hand, confirmed on git's
        # `[branch hash]` line rather than a message match (test_merge_event_
        # contents.py's established shape for a body that carries a trailer).
        self.diverge(same_file=True)
        self.assertNotEqual(self.merge("side").returncode, 0, "expected a conflict")
        (self.repo / "src" / "side.py").write_text("resolved\n")
        self.git("add", "-A")
        stdout = self.git("commit", "-m", body)
        self.run_hook("git commit", stdout)
        hook_events = self.commit_events()
        self.assertEqual(len(hook_events), 1, f"expected one event: {hook_events}")
        hook_content = hook_events[0]["content"]

        # Close-cycle route: a second real merge, same body verbatim, driven
        # straight through append_merge_commit_event.
        self.git("checkout", "-q", "-b", "side2")
        (self.repo / "src" / "side2.py").write_text("side2\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"side2 work\n\nResolves-Event: {derived_id}")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", body, "side2")
        self.assertEqual(self.parent_count(), 2, "premise: a real merge commit")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-side2"
        )

        close_events = [
            e for e in self.commit_events() if e["id"] not in {hook_events[0]["id"]}
        ]
        self.assertEqual(len(close_events), 1, f"expected one event: {close_events}")

        self.assertEqual(hook_content, close_events[0]["content"])

    def test_both_emitters_agree_on_a_trailer_only_body(self):
        """A trailer-only body cleans to `""`. No `or f"Merge {source}"`
        fallback: `event_schema` bounds content LENGTH only, so `""` validates
        silently, and a fallback here would diverge from the hook route (which
        has none) on exactly the case the story claims to converge."""
        trailer_id = self.seed_concern()
        body = f"Resolves-Event: {trailer_id}"

        # Hook route.
        self.diverge(same_file=True)
        self.assertNotEqual(self.merge("side").returncode, 0, "expected a conflict")
        (self.repo / "src" / "side.py").write_text("resolved\n")
        self.git("add", "-A")
        stdout = self.git("commit", "-m", body)
        self.run_hook("git commit", stdout)
        hook_event = self.commit_events()[0]
        self.assertEqual(hook_event["content"], "")

        # Close-cycle route, same body verbatim.
        other_id = self.seed_concern()
        self.git("checkout", "-q", "-b", "side2")
        (self.repo / "src" / "side2.py").write_text("side2\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"side2 work\n\nResolves-Event: {other_id}")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", body, "side2")

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-empty"
        )

        close_events = [e for e in self.commit_events() if e["id"] != hook_event["id"]]
        self.assertEqual(len(close_events), 1, f"expected one event: {close_events}")
        self.assertEqual(close_events[0]["content"], "")


class TestHasResolvesTrailerStaysAuthoredOnly(_MergeCase):
    """Regression guard on `commit_emit.py:98-102` — easy to lose when
    swapping in `parse_commit_body`. `has_resolves_trailer` records that
    somebody WROTE a trailer; a re-parsed id from the merged-in range must
    never set it."""

    def test_has_resolves_trailer_stays_authored_only(self):
        debt_id = self.seed_concern()
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "src" / "side.py").parent.mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "side.py").write_text("side\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"side work\n\nResolves-Event: {debt_id}")
        self.git("checkout", "-q", "main")
        self.commit("main work", path="src/main.py", content="main")
        result = self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(result.returncode, 0, result.stderr)

        append_merge_commit_event(
            str(self.repo), self.smm_dir, "paulingalls/story-side"
        )

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event: {events}")
        meta = events[0]["metadata"]
        self.assertIn(debt_id, meta.get("resolves", []))
        self.assertFalse(
            meta.get("has_resolves_trailer"),
            "a derived id from the merged-in range was credited as authored",
        )


if __name__ == "__main__":
    unittest.main()
