#!/usr/bin/env python3
"""The catch-up observer's own contract: what it claims, refuses, and costs.

`test_commit_event_recording.py` is the specimen table — which commit SHAPES
reach the event log. This file is the module's own boundary: the cheap common
path, the cold start, the range bound, and above all the rule that a reconcile
it declines is REPORTED rather than skipped. The backgrounded case recorded
neither an event nor a trace, and reproducing that silence one module over
would trade a known gap for a new one.

The observer's guard is REACHABILITY (an ancestor of HEAD with no recorded
event), never attribution. That is a deliberately weaker claim than
`_handle_commit`'s, and `commit_observer`'s docstring says why the reflog check
that guards the stronger claim must not be added here. The cases below pin the
consequences of that choice in both directions: what it therefore records, and
what it still refuses.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _append_impl
import _common
import commit_observer
import markers
import review_records
from _commit_repo_case import _MergeCase
from _observer_case import ORDINARY_BASH, _ObserverCase
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT


class TestColdStart(_ObserverCase):
    """The first observation of a session has no lower bound to walk from."""

    def test_the_first_bash_seeds_and_reconciles_nothing(self):
        head = self.head()
        self.observe()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.concerns(), [])
        self.assertEqual(self.marker(), {"head": head})

    def test_history_before_the_first_bash_is_never_walked(self):
        """An unbounded lower bound would record every commit in the repo on
        the first Bash of every session."""
        for i in range(4):
            self.commit(f"feat: {i}", path=f"src/f{i}.py")
        self.observe()
        self.assertEqual(self.commit_events(), [])


class TestTheCheapPath(_ObserverCase):
    """The overwhelming majority of Bash calls move nothing. That case must
    not cost a fork or an event-log read, or watching every Bash would cost
    more than the gap it closes."""

    def test_an_unchanged_head_shells_out_to_nothing(self):
        self.seed_observer()
        with patch("commits._run_git") as run_git:
            self.observe()
        run_git.assert_not_called()

    def test_an_unchanged_head_does_not_read_the_event_log(self):
        self.seed_observer()
        with patch("_common.load_events_with_resolutions") as load:
            self.observe()
        load.assert_not_called()

    def test_a_directory_that_is_not_a_repo_is_simply_quiet(self):
        with patch("git_head.read_head", return_value=None):
            self.observe()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.concerns(), [])
        self.assertIsNone(self.marker())


class TestTheRange(_ObserverCase):
    """Every unrecorded commit between last-seen and HEAD, oldest first."""

    def test_several_commits_are_all_recorded(self):
        self.seed_observer()
        landed = [self.commit(f"feat: {i}", path=f"src/f{i}.py") for i in range(3)]
        self.observe()
        self.assertEqual(self.recorded_hashes(), landed)

    def test_an_already_recorded_commit_is_not_duplicated(self):
        self.seed_observer()
        first = self.commit("feat: one", path="src/a.py")
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="feat: one",
                metadata={"commit_hash": first, "action": "commit_success"},
            ),
        )
        second = self.commit("feat: two", path="src/b.py")
        self.observe()
        self.assertEqual(self.recorded_hashes(), [first, second])

    def test_a_second_observation_adds_nothing(self):
        self.seed_observer()
        self.commit("feat: x")
        self.observe()
        self.observe()
        self.assertEqual(len(self.commit_events()), 1)

    def test_the_marker_advances_to_the_new_head(self):
        self.seed_observer()
        head = self.commit("feat: x")
        self.observe()
        self.assertEqual(self.marker(), {"head": head})


class TestDeclinesAreReported(_ObserverCase):
    """AC3, the rule this module exists to honor: a reconcile that does not
    happen is recorded in a form distinguishable from one that did."""

    def test_an_over_long_range_records_none_of_it_and_says_so(self):
        """Past the bound this is a branch switch or a fast-forward of history
        authored elsewhere, whose events may have been compacted out of the
        LIVE log — the only thing the dedup can consult. Recording them would
        manufacture duplicates, so the whole range is refused."""
        self.seed_observer()
        for i in range(commit_observer.MAX_RECONCILE + 1):
            self.commit(f"feat: {i}", path=f"src/f{i}.py")
        self.observe()
        self.assertEqual(self.commit_events(), [])
        declined = self.concerns()
        self.assertEqual(len(declined), 1)
        self.assertIn("declined", declined[0]["content"])
        self.assertIn(str(commit_observer.MAX_RECONCILE), declined[0]["content"])

    def test_a_range_at_the_bound_is_still_recorded(self):
        """Non-vacuity for the case above: the refusal is the BOUND, not a
        blanket refusal of multi-commit ranges."""
        self.seed_observer()
        for i in range(commit_observer.MAX_RECONCILE):
            self.commit(f"feat: {i}", path=f"src/f{i}.py")
        self.observe()
        self.assertEqual(len(self.commit_events()), commit_observer.MAX_RECONCILE)
        self.assertEqual(self.concerns(), [])

    def test_a_last_seen_commit_this_repo_never_had_is_reported(self):
        """A rebase rewrote it, gc collected it, or the marker came from
        another checkout. git cannot describe the range at all."""
        markers.marker_write(
            self.smm_dir, markers.LAST_SEEN_HEAD, {"head": "0" * 40}, "main"
        )
        self.commit("feat: x")
        self.observe()
        self.assertEqual(self.commit_events(), [])
        self.assertIn("unknown to this checkout", self.concerns()[0]["content"])

    def test_an_unreadable_message_is_reported_against_its_own_hash(self):
        self.seed_observer()
        head = self.commit("feat: x")
        with patch("commits.get_commit_message_body", return_value=None):
            self.observe()
        self.assertEqual(self.commit_events(), [])
        declined = self.concerns()
        self.assertEqual(len(declined), 1)
        self.assertEqual(declined[0]["metadata"]["commit_hash"], head)
        self.assertEqual(declined[0]["severity"], "low")

    def test_a_decline_does_not_repeat_on_every_later_bash(self):
        """The marker advances even when the reconcile declined. Left behind,
        it would re-file the same concern on every Bash for the rest of the
        session, which is how an advisory becomes noise nobody reads."""
        self.seed_observer()
        self.commit("feat: x")
        with patch("commits.get_commit_message_body", return_value=None):
            self.observe()
        self.observe()
        self.observe()
        self.assertEqual(len(self.concerns()), 1)

    def test_a_reconcile_that_raises_leaves_the_range_open(self):
        """The counterpart to the case above, and the reason the two must not
        share a path: a decline is a decision somebody can read, while a raise
        decided nothing and said nothing. Advancing the marker past it would
        drop the range this module exists to catch — silently, which is the
        original defect rather than a variation on it. The per-commit dedup is
        what makes walking the same range again idempotent.
        """
        self.seed_observer()
        landed = self.commit("feat: x")
        with (
            patch(
                "_common.load_events_with_resolutions",
                side_effect=RuntimeError("events lock timed out"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.observe()
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_a_decline_names_the_observer_not_the_bash_it_rode_on(self):
        """The observing command did not make the commit. Stamping `ls -la`
        onto it is the misattribution the older trace's `Command:` label
        already produced once."""
        self.seed_observer()
        self.commit("feat: x")
        with patch("commits.get_commit_message_body", return_value=None):
            self.observe()
        content = self.concerns()[0]["content"]
        self.assertIn("commit observer", content)
        self.assertNotIn(ORDINARY_BASH, content)


class TestAMergeBringsInNoExtraCommits(_MergeCase, _ObserverCase):
    """`--first-parent`, and why it is load-bearing rather than tidiness.

    A back-merge's INCOMING range is every commit the branch had not seen —
    dozens, whose own events landed with them and may since have been compacted
    out of the live log, which is the only index the dedup can consult.
    Enumerating them would re-record work accounted for weeks ago, and would
    blow past the range bound on any real merge.

    What the first-parent chain does contain is this branch's own commits plus
    the merge itself — those DID move HEAD here, and are the question being
    asked.
    """

    def _merge_side_into_main(self) -> tuple[str, str]:
        """`(the side commit, the merge)`. `diverge` advances main too."""
        self.diverge()
        side = self.git("rev-parse", "side")
        self.assertEqual(self.merge("side", "--no-edit").returncode, 0)
        return side, self.head()

    def test_the_merged_branchs_own_commits_are_not_recorded(self):
        self.seed_observer()
        side, merge = self._merge_side_into_main()
        self.observe()
        recorded = self.recorded_hashes()
        self.assertIn(merge, recorded)
        self.assertNotIn(side, recorded)

    def test_the_recorded_merge_is_tagged_as_one(self):
        """Tagging comes from `build_commit_event`, which both other emitters
        already share — the tag keeps a merge out of the resolve-link-rate
        denominator and exempt from the commit-size concern."""
        self.seed_observer()
        _, merge = self._merge_side_into_main()
        self.observe()
        tagged = [
            e for e in self.commit_events() if e["metadata"].get("commit_hash") == merge
        ]
        self.assertTrue(tagged[0]["metadata"].get("is_merge"))


class TestReviewCycle(_ObserverCase):
    """A commit event recorded without a cycle reset leaves the previous
    cycle's quality-review flag latched, so the NEXT commit's gate reads
    satisfied off a review that predates this commit. Same hazard, and same
    fix, as `rebuild_at_head` documents."""

    def test_the_reset_is_keyed_to_the_newest_commit_recorded(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: one", path="src/a.py")
        newest = self.commit("feat: two", path="src/b.py")
        self.observe()
        flags = review_records.read_review_flags(self.smm_dir, "main")
        self.assertFalse(flags["quality_review_done"])
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), newest
        )

    def test_recording_nothing_leaves_the_cycle_alone(self):
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.observe()
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_a_leaked_xp_agent_type_records_but_does_not_reset(self):
        """Mirrors both other commit paths: the commit event always lands, and
        only the state mutations are gated on the identity being wrong."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")
        self.commit("feat: x")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")
        self.assertEqual(len(self.commit_events()), 1)
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


class TestMarkerKeying(_ObserverCase):
    """The SMM is shared across worktrees, so one shared record would read as
    an unexplained jump in every checkout but the one that wrote it."""

    def test_the_marker_is_keyed_on_the_checkout_not_the_session(self):
        self.seed_observer()
        self.assertIsNotNone(self.marker())
        self.assertIsNone(
            markers.marker_read(
                self.smm_dir, markers.LAST_SEEN_HEAD, "worktree-story-999"
            )
        )

    def test_another_checkouts_head_is_not_read_as_this_ones(self):
        markers.marker_write(
            self.smm_dir,
            markers.LAST_SEEN_HEAD,
            {"head": "0" * 40},
            "worktree-story-999",
        )
        self.assertIsNone(
            commit_observer.read_last_seen_head(self.smm_dir, str(self.repo))
        )


class TestTwoObserversSharingACheckout(_ObserverCase):
    """AC3. `observe()` runs on every non-commit Bash, so two hooks in one
    checkout can reach the same unrecorded commit at the same time.

    WHAT THESE PROVE, AND WHAT THEY DO NOT. They prove the RE-CHECK under the
    lock: the dedup no longer rests on a snapshot taken before the append, so a
    commit another observer recorded in the window is seen and skipped. That is
    the part that makes the fix work.

    They do NOT prove mutual exclusion between two OS processes. `flock`'s
    SIGALRM timeout only arms on the main thread, so a threaded test cannot
    exercise the real primitive at all, and a two-process test belongs in
    tests/integration/. Claiming the stronger property from this evidence would
    be exactly the overclaim the previous story spent four increments removing.
    """

    def _observe_directly(self) -> None:
        """Straight into the module, not through `run_hook`: the patch below
        wraps a function the surrounding hook pipeline also calls, and the
        window being modelled is `_reconcile`'s own."""
        commit_observer.observe(self.smm_dir, "main", str(self.repo))

    def test_a_commit_recorded_after_the_first_read_is_not_duplicated(self):
        """The real race window. Today's check reads a snapshot taken BEFORE
        the append, so a competitor landing in between is invisible to it."""
        self.seed_observer()
        landed = self.commit("feat: x")
        real = _common.load_events_with_resolutions
        planted = []

        def competing(smm_dir, *args, **kwargs):
            result = real(smm_dir, *args, **kwargs)
            if not planted:
                planted.append(True)
                _common.append_safe(
                    smm_dir,
                    make_event(
                        EVENT_TYPE_COMMIT,
                        content="feat: x",
                        metadata={
                            "commit_hash": landed,
                            "action": "commit_success",
                        },
                    ),
                )
            return result

        with patch("_common.load_events_with_resolutions", side_effect=competing):
            self._observe_directly()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_a_lock_it_cannot_take_leaves_the_range_open(self):
        """The observer must never raise into the user's Bash call, and must
        not advance the marker over a range it did not record — the next Bash
        retries, and the per-commit dedup makes that resume rather than
        duplicate."""
        self.seed_observer()
        before = self.marker()
        landed = self.commit("feat: x")
        with patch(
            "commit_observer._observer_lock",
            side_effect=_append_impl.LockTimeoutError("busy"),
        ):
            self._observe_directly()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.marker(), before)
        self._observe_directly()
        self.assertEqual(self.recorded_hashes(), [landed])


if __name__ == "__main__":
    unittest.main()
