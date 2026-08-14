#!/usr/bin/env python3
"""What a merge's recorded event CONTAINS — as distinct from whether one exists.

Split from `test_manual_merge_commit_event.py` when it crossed the 450-line band.
That file answers "is a merge recorded at all, and by which route"; these cases
take a recorded merge as given and interrogate its contents: which
`Resolves-Event:` ids it claims, which of those count as authored, and which
concerns it must NOT draw.

The seam is where the close review found three defects, all of them about
contents rather than existence — so the group has its own file for the same reason
the provenance cases got one.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import unittest

import _common
from _commit_repo_case import _MergeCase
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT


class TestWhatTheMergeEventResolves(_MergeCase):
    """`resolves` UNIONS what the operator wrote with what the range yields.

    A merge HEAD is often the only surviving record of the work it brings in — a
    teammate's per-commit events can fail to reach the shared log — so the
    merged-in bodies are re-parsed for trailers those events would have carried.
    That derivation must ADD to the merge body's own trailer, never replace it.
    Replacing is safe in `merge_commit_event` only because the body it builds
    from is a generated `Merge <source>` subject with no trailer by
    construction; an operator's `-m` is not, and dropping what they typed is the
    same silent loss the tag exists to prevent.

    Driven through the conflict-finish shape: it confirms on git's
    `[branch hash]` line rather than on a message match, so the body is free to
    carry a trailer without the command string having to reproduce it.
    """

    def _merge_resolving(self, body: str) -> dict:
        """Finish a conflicted merge with `body`, run the hook, return the event."""
        self.diverge(same_file=True)
        self.assertNotEqual(self.merge("side").returncode, 0, "expected a conflict")
        (self.repo / "src" / "side.py").write_text("resolved\n")
        self.git("add", "-A")
        stdout = self.git("commit", "-m", body)
        self.assertEqual(self.parent_count(), 2, "expected a real merge commit")

        self.run_hook("git commit", stdout)

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        return events[0]

    def diverge(self, *, same_file: bool = False) -> None:
        """As the base, but the SIDE commit carries a trailer to be derived."""
        self.derived_id = self.seed_concern()
        self.git("checkout", "-q", "-b", "side")
        target = self.repo / "src" / "side.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("side")
        self.git("add", "-A")
        self.git(
            "commit", "-q", "-m", f"side work\n\nResolves-Event: {self.derived_id}"
        )
        self.git("checkout", "-q", "main")
        self.commit(
            "main work",
            path="src/side.py" if same_file else "src/main.py",
            content="main",
        )

    def test_a_trailer_on_the_merge_body_survives_the_derivation(self):
        """The case replacement would have broken: both ids present."""
        authored_id = self.seed_concern()
        event = self._merge_resolving(
            f"Merge branch 'side'\n\nResolves-Event: {authored_id}"
        )

        resolves = event["metadata"]["resolves"]
        self.assertIn(authored_id, resolves, "the operator's own trailer was dropped")
        self.assertIn(self.derived_id, resolves, "the merged range was not re-parsed")

    def test_a_derived_id_is_not_credited_as_an_authored_trailer(self):
        """`has_resolves_trailer` measures AUTHORING discipline, so a re-parsed
        id must not set it — otherwise every merge scores as if somebody wrote
        the trailer at merge time, and the metric flatters itself."""
        event = self._merge_resolving("Merge branch 'side'")

        self.assertIn(self.derived_id, event["metadata"]["resolves"])
        self.assertFalse(
            event["metadata"].get("has_resolves_trailer"),
            "a derived id was counted as an authored trailer",
        )

    def test_an_authored_trailer_is_credited(self):
        """The contrast that keeps the case above from passing vacuously."""
        authored_id = self.seed_concern()
        event = self._merge_resolving(
            f"Merge branch 'side'\n\nResolves-Event: {authored_id}"
        )

        self.assertTrue(event["metadata"].get("has_resolves_trailer"))


class TestABackMergeIsNotCreditedWithTheRangeItAbsorbs(_MergeCase):
    """The derivation reads only commits whose OWN event never landed.

    Re-parsing the merged range exists for one case: a teammate's per-commit
    events failed to reach the shared log, so the merge HEAD is the only surviving
    record of that work. Applied to every two-parent HEAD it is catastrophically
    wider than that, because a back-merge (`git merge main`) is also two-parent
    and its incoming range is every commit the branch had not yet seen — whose
    trailers landed with their own commits long ago. Unioning those credits one
    back-merge with resolving them, and silently closes any left open on purpose.
    """

    def _merge_a_side_branch_carrying(self, trailer_id: str) -> str:
        """Build `side` with one commit whose body resolves `trailer_id`, and
        merge it. Returns the side commit's hash."""
        self.git("checkout", "-q", "-b", "side")
        target = self.repo / "src" / "side.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("side")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"side work\n\nResolves-Event: {trailer_id}")
        side_head = self.head()
        self.git("checkout", "-q", "main")
        self.commit("main work", path="src/main.py", content="main")
        result = self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(result.returncode, 0, result.stderr)
        return side_head

    def test_an_unrecorded_commits_trailer_is_still_rescued(self):
        """The case the derivation exists for — no event for the side commit, so
        its trailer would be lost without the re-parse. This is the control that
        stops the case below passing vacuously."""
        rescued = self.seed_concern()
        self._merge_a_side_branch_carrying(rescued)

        self.run_hook("git merge --no-ff side")

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertIn(rescued, events[0]["metadata"]["resolves"])

    def test_a_commit_whose_event_already_landed_is_not_re_derived(self):
        """The fix. With the side commit's own event in the log, this merge must
        not claim its trailer — that id was resolved by the commit that wrote it."""
        already = self.seed_concern()
        side_head = self._merge_a_side_branch_carrying(already)
        # The side commit's own event, exactly as its own PostToolUse run would
        # have recorded it: same hash, its trailer already resolved there.
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="side work",
                files=["src/side.py"],
                metadata={"commit_hash": side_head, "resolves": [already]},
            ),
        )

        self.run_hook("git merge --no-ff side")

        merge_events = [
            e
            for e in self.commit_events()
            if e["metadata"].get("commit_hash") == self.head()
        ]
        self.assertEqual(
            len(merge_events), 1, f"expected one merge event: {merge_events}"
        )
        self.assertNotIn(
            already,
            merge_events[0]["metadata"].get("resolves", []),
            "the merge was credited with an id its own commit already resolved",
        )


class TestAMergeIsExemptFromTheCommitSizeConcern(_MergeCase):
    """`files` for a merge is the first-parent diff — legitimately the whole
    merged branch — so "consider smaller commits" is advice about work that was
    already committed in the small. The release claimed the `is_merge` tag
    suppressed this concern in four places while nothing implemented it."""

    def test_a_wide_merge_draws_no_commit_size_concern(self):
        self.git("checkout", "-q", "-b", "side")
        src = self.repo / "src"
        src.mkdir(parents=True, exist_ok=True)
        for i in range(14):
            (src / f"mod{i}.py").write_text(f"x = {i}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "side work across many files")
        self.git("checkout", "-q", "main")
        self.commit("main work", path="src/main.py", content="main")
        result = self.merge("--no-ff", "side", "-m", "Merge side")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.run_hook('git merge --no-ff side -m "Merge side"', result.stdout)

        events = self.commit_events()
        self.assertEqual(len(events), 1, f"expected one commit event, got {events}")
        self.assertGreaterEqual(
            len(events[0]["files"]), 14, "premise: the merge really is wide"
        )
        self.assertTrue(events[0]["metadata"].get("is_merge"))
        sized = [
            c for c in self.concerns() if "consider smaller commits" in c["content"]
        ]
        self.assertEqual(sized, [], f"a merge drew a commit-size concern: {sized}")


class TestACommitBodyCannotForgeARangeRecord(_MergeCase):
    """`merged_range_commits` parses git output by framing records on git's own
    `-z` NUL separator and partitioning each on the FIRST unit-separator byte.
    Framing on a record-separator byte came first, and a commit message may
    legally contain one, so a body could inject a record — and the injected hash,
    being fabricated, is absent from the recorded set BY CONSTRUCTION, which is
    precisely what the "no recorded event" filter keys on. An injected record
    would therefore bypass the bound every time.

    Not a security finding — writing the body means you can already write a real
    trailer. It is a correctness one: the filter must not be defeatable by content
    it is reading."""

    def test_an_injected_record_does_not_smuggle_a_trailer_past_the_filter(self):
        smuggled = self.seed_concern()
        self.derived_id = self.seed_concern()

        self.git("checkout", "-q", "-b", "side")
        target = self.repo / "src" / "side.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("side")
        self.git("add", "-A")
        # A body that closes its own record and opens a forged one, whose 40-hex
        # hash no event can possibly carry.
        forged = "b" * 40
        self.git(
            "commit",
            "-q",
            "-m",
            f"side work\n\nResolves-Event: {self.derived_id}\n"
            f"\x1e{forged}\x1fforged\n\nResolves-Event: {smuggled}\n",
        )
        side_head = self.head()
        self.git("checkout", "-q", "main")
        self.commit("main work", path="src/main.py", content="main")
        self.assertEqual(
            self.merge("--no-ff", "side", "-m", "Merge side").returncode, 0
        )

        # The side commit's own event HAS landed, so the filter must skip it whole.
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="side work",
                files=["src/side.py"],
                metadata={"commit_hash": side_head, "resolves": [self.derived_id]},
            ),
        )

        self.run_hook("git merge --no-ff side")

        merge_events = [
            e
            for e in self.commit_events()
            if e["metadata"].get("commit_hash") == self.head()
        ]
        self.assertEqual(
            len(merge_events), 1, f"expected one merge event: {merge_events}"
        )
        resolves = merge_events[0]["metadata"].get("resolves", [])
        self.assertNotIn(
            smuggled,
            resolves,
            "a forged range record smuggled a trailer past the filter",
        )
        self.assertNotIn(
            self.derived_id, resolves, "the recorded commit was not skipped"
        )


if __name__ == "__main__":
    unittest.main()
