#!/usr/bin/env python3
"""What a commit the observer records does to the review cycle — and what a
commit it FAILED to record must not do.

Split from `test_commit_observer.py` when that file reached its recorded
sub-cap. Cohesive rather than arbitrary: every row here is about the three
review records (flags, watermark, coverage) that `end_review_cycle` moves
together, and the two ways the observer can be wrong about them — resetting for
the wrong commit in the range, or resetting for one the event log never took.
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
import pre_tool_bash_commit_gates
import review_records
from _observer_case import ORDINARY_BASH, _ObserverCase


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

    def test_a_commit_recorded_ahead_of_this_one_keeps_the_watermark_there(self):
        """The backgrounded case, one commit later. A foreground commit that
        ALREADY reset the cycle sits at the top of the same range, so keying the
        reset to what this observer happened to record walks the watermark back
        to the older hash and clears the review that ran in between."""
        self.seed_observer()
        older = self.commit("feat: backgrounded", path="src/a.py")
        newest = self.commit("feat: foreground", path="src/b.py")
        # What `_handle_commit` already did for the foreground commit.
        self.record_commit_event(newest)
        review_records.write_review_watermark(self.smm_dir, "main", newest)
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self.observe()

        self.assertIn(older, self.recorded_hashes())
        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), newest
        )
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
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


class TestALeakedIdentityStillOwesTheReset(_ObserverCase):
    """Skipping the reset under a leaked `xp-` identity is deliberate. The
    marker advancing PAST the skip is not: the range never comes back, so the
    reset is lost permanently rather than deferred.

    Asserted as the CONSEQUENCE the reset exists to produce, not as a marker
    value. `quality_review_done` left latched means the next 2+-code-file
    commit reads the gate satisfied off a review that predates the commit and
    ships unreviewed — a test that only read a marker would pass against a fix
    that left exactly that hole open.
    """

    def _stage_two_code_files(self) -> None:
        for name in ("src/one.py", "src/two.py"):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x = 1\n")
        self.git("add", "-A")

    def _run_the_commit_gate(self) -> list[str]:
        """The real gate over the real index.

        `_HookTestCase` auto-mocks `commits.get_staged_diff` to "" for every
        hook test, and an empty staged diff is a gate that counts no code files
        and so blocks nothing — the assertion below would pass against any
        implementation, including none. Stopped for the call and restarted
        whichever way it returns, since a block is a raise.
        """
        self._staged_diff_patch.stop()
        try:
            return pre_tool_bash_commit_gates.commit_gate_parts(
                self.smm_dir, "git commit -m x", str(self.repo)
            )
        finally:
            self._staged_diff_patch.start()

    def _observe_under_a_leak(self) -> None:
        """The defect's setup: a commit recorded while the identity was wrong."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: recorded under a leak", path="src/a.py")
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")

    def test_the_next_two_file_commit_does_not_pass_on_the_stale_review(self):
        self._observe_under_a_leak()
        self.observe()
        self._stage_two_code_files()

        with self.assertRaises(_common.BlockedError):
            self._run_the_commit_gate()

    def test_the_owed_reset_waits_for_an_identity_allowed_to_apply_it(self):
        """Another leaked Bash may not settle it either — that is the same
        wrong identity mutating the same cycle state, one call later."""
        self._observe_under_a_leak()
        self.run_hook(ORDINARY_BASH, agent_type="xp-leaked")

        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_settling_it_once_does_not_clear_a_review_that_ran_after(self):
        """Idempotence, stated as the harm it prevents: a second settle would
        clear the flags a review set in between and demand a re-review that
        nothing asked for."""
        self._observe_under_a_leak()
        self.observe()
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self.observe()

        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_an_owed_hash_the_watermark_is_already_past_is_not_applied(self):
        """Walking the watermark BACKWARDS is the defect `86d4d129` fixed
        earlier this sprint. An owed reset must not reintroduce it by a new
        door, so it applies only to a DESCENDANT of the current watermark."""
        self._observe_under_a_leak()
        ahead = self.commit("feat: reviewed since", path="src/b.py")
        review_records.write_review_watermark(self.smm_dir, "main", ahead)
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")

        self.observe()

        self.assertEqual(
            review_records.read_review_watermark(self.smm_dir, "main"), ahead
        )
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )

    def test_an_owed_hash_no_longer_in_the_repo_is_dropped_with_a_trace(self):
        """Kept, it wedges the marker forever AND leaves the latch defect live.
        Dropped silently, the unreviewed commit is the one thing nobody hears
        about — so it goes, and says so."""
        self._observe_under_a_leak()
        review_records.write_review_watermark(
            self.smm_dir, "main", self.git("rev-parse", "HEAD~1")
        )
        # Reset alone leaves the object in place and perfectly resolvable; the
        # reflog expiry and prune are what make git genuinely unable to answer,
        # which is the state being tested.
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("reflog", "expire", "--expire=now", "--all")
        self.git("gc", "-q", "--prune=now")

        self.observe()

        self.assertTrue(
            any("owed" in c["content"].lower() for c in self.concerns()),
            "an owed reset dropped without a trace is a silent loss",
        )
        self.observe()
        self.assertEqual(
            len([c for c in self.concerns() if "owed" in c["content"].lower()]),
            1,
            "a dropped owed reset must not re-file its trace on every Bash",
        )


class TestADroppedAppendIsNotSuccess(_ObserverCase):
    """The event log's own lock can refuse the append. `bulk_append_safe` logs
    that and returns, so "recorded" and "dropped" look identical to a caller
    reading its return — and a dropped one that advanced the marker is a commit
    no event will ever carry, which is the silence this module exists to end."""

    def test_a_dropped_event_leaves_the_range_open(self):
        self.seed_observer()
        before = self.marker()
        landed = self.commit("feat: x")
        with patch(
            "_append_impl.bulk_append",
            side_effect=_append_impl.LockTimeoutError("events.jsonl busy"),
        ):
            self.observe()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.marker(), before)
        self.observe()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_a_dropped_event_does_not_end_the_review_cycle(self):
        """The reset belongs to a commit the log carries. Ending the cycle for
        one that was dropped points the gate's `{sha}..HEAD` diff at a commit
        with no event and spends the coverage a review earned."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self.seed_observer()
        self.commit("feat: x")
        with patch(
            "_append_impl.bulk_append",
            side_effect=_append_impl.LockTimeoutError("events.jsonl busy"),
        ):
            self.observe()
        self.assertEqual(review_records.read_review_watermark(self.smm_dir, "main"), "")
        self.assertTrue(
            review_records.read_review_flags(self.smm_dir, "main")[
                "quality_review_done"
            ]
        )


if __name__ == "__main__":
    unittest.main()
